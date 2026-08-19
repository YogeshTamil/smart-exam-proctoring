"""
Computer-vision core for Smart Exam Proctoring.

Responsibilities:
  - decode frames sent from the browser (base64 data URLs)
  - detect faces with a Haar cascade
  - train / query an LBPH recognizer for identity verification
  - persist face-sample crops and violation snapshots to disk
"""
import base64
import json
import os
from datetime import datetime

import cv2
import numpy as np

FACE_SIZE = (200, 200)
CASCADE_PATH = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"

# LBPH prediction returns a *distance* - lower means a closer match.
# This default works reasonably well for a webcam at normal room lighting;
# tune it in your deployment (see README) if you see false mismatches.
IDENTITY_CONFIDENCE_THRESHOLD = 75

_cascade = None
_recognizer = None
_recognizer_trained = False


def _instance_dir():
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
    os.makedirs(base, exist_ok=True)
    return base


def _faces_dir():
    path = os.path.join(_instance_dir(), "faces")
    os.makedirs(path, exist_ok=True)
    return path


def _model_path():
    return os.path.join(_instance_dir(), "trainer.yml")


def get_cascade():
    global _cascade
    if _cascade is None:
        _cascade = cv2.CascadeClassifier(CASCADE_PATH)
    return _cascade


def get_recognizer():
    """Lazily load the LBPH recognizer from disk if a trained model exists."""
    global _recognizer, _recognizer_trained
    if _recognizer is None:
        _recognizer = cv2.face.LBPHFaceRecognizer_create()
        if os.path.exists(_model_path()):
            _recognizer.read(_model_path())
            _recognizer_trained = True
    return _recognizer if _recognizer_trained else None


def decode_base64_image(data_url):
    """Convert a 'data:image/jpeg;base64,...' string into a BGR numpy image."""
    if "," in data_url:
        data_url = data_url.split(",", 1)[1]
    raw = base64.b64decode(data_url)
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def detect_faces(gray_img):
    """Return a list of (x, y, w, h) boxes for detected faces."""
    cascade = get_cascade()
    faces = cascade.detectMultiScale(
        gray_img, scaleFactor=1.15, minNeighbors=6, minSize=(80, 80)
    )
    return list(faces)


def crop_face(gray_img, box):
    x, y, w, h = box
    crop = gray_img[y:y + h, x:x + w]
    return cv2.resize(crop, FACE_SIZE)


def save_face_sample(student_id, face_gray_crop):
    """Persist one training crop for a student and return its path."""
    student_dir = os.path.join(_faces_dir(), str(student_id))
    os.makedirs(student_dir, exist_ok=True)
    existing = [f for f in os.listdir(student_dir) if f.endswith(".jpg")]
    idx = len(existing) + 1
    path = os.path.join(student_dir, f"sample_{idx:03d}.jpg")
    cv2.imwrite(path, face_gray_crop)
    return path


def retrain_recognizer():
    """Rebuild the LBPH model from every student's saved face samples."""
    global _recognizer, _recognizer_trained
    images, labels = [], []
    faces_root = _faces_dir()
    for student_id_str in os.listdir(faces_root):
        student_dir = os.path.join(faces_root, student_id_str)
        if not os.path.isdir(student_dir):
            continue
        try:
            label = int(student_id_str)
        except ValueError:
            continue
        for fname in os.listdir(student_dir):
            if not fname.endswith(".jpg"):
                continue
            img = cv2.imread(os.path.join(student_dir, fname), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            images.append(cv2.resize(img, FACE_SIZE))
            labels.append(label)

    if not images:
        return False

    recognizer = cv2.face.LBPHFaceRecognizer_create()
    recognizer.train(images, np.array(labels))
    recognizer.write(_model_path())

    _recognizer = recognizer
    _recognizer_trained = True
    return True


def predict_identity(gray_face_crop):
    """Return (student_id, confidence) or (None, None) if no model is trained."""
    recognizer = get_recognizer()
    if recognizer is None:
        return None, None
    label, confidence = recognizer.predict(gray_face_crop)
    return label, confidence


def save_violation_snapshot(app_static_folder, session_id, frame_bgr, violation_type):
    """Save an evidence snapshot under static/violations/<session_id>/ and
    return the path relative to the static folder (for url_for)."""
    rel_dir = os.path.join("violations", str(session_id))
    abs_dir = os.path.join(app_static_folder, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    fname = f"{ts}_{violation_type}.jpg"
    cv2.imwrite(os.path.join(abs_dir, fname), frame_bgr)
    return os.path.join(rel_dir, fname).replace(os.sep, "/")


def analyze_frame(app_static_folder, session, student_id, data_url):
    """
    Full per-frame proctoring pipeline used by /api/proctor/frame.

    Returns a dict describing what was found and, if applicable, a violation
    that was already persisted (caller still needs to write the ViolationLog row).
    """
    frame = decode_base64_image(data_url)
    if frame is None:
        return {"error": "could_not_decode_frame"}

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = detect_faces(gray)
    num_faces = len(faces)

    result = {
        "num_faces": num_faces,
        "violation_type": None,
        "detail": None,
        "snapshot_path": None,
    }

    if num_faces == 0:
        result["violation_type"] = "no_face"
    elif num_faces > 1:
        result["violation_type"] = "multiple_faces"
    else:
        crop = crop_face(gray, faces[0])
        label, confidence = predict_identity(crop)
        if label is not None:
            if label != int(student_id) or confidence > IDENTITY_CONFIDENCE_THRESHOLD:
                result["violation_type"] = "identity_mismatch"
                result["detail"] = f"matched_label={label} confidence={confidence:.1f}"

    if result["violation_type"]:
        result["snapshot_path"] = save_violation_snapshot(
            app_static_folder, session.id, frame, result["violation_type"]
        )

    return result
