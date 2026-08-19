"""
Smart Exam Proctoring — Flask application entry point.

Run with:
    python app.py
then open http://127.0.0.1:5000
"""
import os
from datetime import datetime

import cv2
from flask import Flask, render_template, request, jsonify, url_for, abort

import proctor
from models import db, Student, ExamSession, ViolationLog, VIOLATION_LABELS, VIOLATION_SEVERITY
from questions import QUESTIONS, EXAM_DURATION_SECONDS

EVENT_VIOLATION_TYPES = {"tab_switch", "window_blur", "audio_spike"}
EVENT_THROTTLE_SECONDS = 3


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(app.static_folder, "violations"), exist_ok=True)

    app.config["SECRET_KEY"] = "dev-key-change-me"
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///" + os.path.join(app.instance_path, "proctoring.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    with app.app_context():
        db.create_all()

    register_routes(app)
    return app


def register_routes(app):

    # ---------------------------------------------------------- pages ----

    @app.route("/")
    def index():
        students = Student.query.order_by(Student.created_at.desc()).all()
        return render_template("index.html", students=students)

    @app.route("/register")
    def register_page():
        return render_template("register.html")

    @app.route("/exam/<int:student_id>")
    def exam_page(student_id):
        student = Student.query.get_or_404(student_id)
        if not student.is_enrolled:
            abort(400, "Student is not enrolled with enough face samples yet.")

        # Resume an in-progress session if one exists, else create a new one.
        session = ExamSession.query.filter_by(
            student_id=student.id, status="in_progress"
        ).first()
        if session is None:
            session = ExamSession(student_id=student.id, total_questions=len(QUESTIONS))
            db.session.add(session)
            db.session.commit()

        return render_template(
            "exam.html",
            student=student,
            session=session,
            questions=QUESTIONS,
            duration_seconds=EXAM_DURATION_SECONDS,
        )

    @app.route("/exam/submitted/<int:session_id>")
    def exam_submitted(session_id):
        session = ExamSession.query.get_or_404(session_id)
        return render_template(
            "exam_submitted.html",
            session=session,
            student=session.student,
            counts=session.violation_counts(),
            labels=VIOLATION_LABELS,
        )

    @app.route("/dashboard")
    def dashboard():
        sessions = ExamSession.query.order_by(ExamSession.start_time.desc()).all()
        return render_template(
            "dashboard.html", sessions=sessions, labels=VIOLATION_LABELS
        )

    @app.route("/dashboard/session/<int:session_id>")
    def session_detail(session_id):
        session = ExamSession.query.get_or_404(session_id)
        return render_template(
            "session_detail.html",
            session=session,
            student=session.student,
            labels=VIOLATION_LABELS,
            severity=VIOLATION_SEVERITY,
        )

    # ------------------------------------------------------------ API ----

    @app.route("/api/register", methods=["POST"])
    def api_register():
        payload = request.get_json(force=True, silent=True) or {}
        name = (payload.get("name") or "").strip()
        email = (payload.get("email") or "").strip() or None
        images = payload.get("images") or []

        if not name:
            return jsonify({"error": "Name is required."}), 400
        if len(images) < 3:
            return jsonify({"error": "At least 3 face captures are required."}), 400

        student = Student(name=name, email=email)
        db.session.add(student)
        db.session.commit()  # need student.id for labeling face samples

        saved, skipped = 0, 0
        for data_url in images:
            frame = proctor.decode_base64_image(data_url)
            if frame is None:
                skipped += 1
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = proctor.detect_faces(gray)
            if len(faces) != 1:
                skipped += 1
                continue
            crop = proctor.crop_face(gray, faces[0])
            proctor.save_face_sample(student.id, crop)
            saved += 1

        student.face_sample_count = saved
        db.session.commit()

        trained = False
        if student.is_enrolled:
            trained = proctor.retrain_recognizer()

        return jsonify({
            "success": True,
            "student_id": student.id,
            "saved": saved,
            "skipped": skipped,
            "enrolled": student.is_enrolled,
            "model_trained": trained,
        })

    @app.route("/api/proctor/frame", methods=["POST"])
    def api_proctor_frame():
        payload = request.get_json(force=True, silent=True) or {}
        session_id = payload.get("session_id")
        image = payload.get("image")
        session = db.session.get(ExamSession, session_id) if session_id else None
        if session is None:
            return jsonify({"error": "Invalid session_id."}), 400
        if session.status != "in_progress":
            return jsonify({"error": "Session is not active."}), 409
        if not image:
            return jsonify({"error": "Missing image."}), 400

        result = proctor.analyze_frame(
            app.static_folder, session, session.student_id, image
        )
        if result.get("error"):
            return jsonify(result), 400

        if result["violation_type"]:
            log = ViolationLog(
                session_id=session.id,
                type=result["violation_type"],
                detail=result["detail"],
                snapshot_path=result["snapshot_path"],
            )
            db.session.add(log)
            db.session.commit()

        return jsonify({
            "num_faces": result["num_faces"],
            "violation_type": result["violation_type"],
            "counts": session.violation_counts(),
        })

    @app.route("/api/proctor/event", methods=["POST"])
    def api_proctor_event():
        payload = request.get_json(force=True, silent=True) or {}
        session_id = payload.get("session_id")
        vtype = payload.get("type")
        detail = payload.get("detail")

        session = db.session.get(ExamSession, session_id) if session_id else None
        if session is None:
            return jsonify({"error": "Invalid session_id."}), 400
        if session.status != "in_progress":
            return jsonify({"error": "Session is not active."}), 409
        if vtype not in EVENT_VIOLATION_TYPES:
            return jsonify({"error": "Unknown event type."}), 400

        # Server-side throttle as a safety net against event spam.
        last = (
            ViolationLog.query.filter_by(session_id=session.id, type=vtype)
            .order_by(ViolationLog.timestamp.desc())
            .first()
        )
        if last and (datetime.utcnow() - last.timestamp).total_seconds() < EVENT_THROTTLE_SECONDS:
            return jsonify({"counts": session.violation_counts(), "throttled": True})

        log = ViolationLog(session_id=session.id, type=vtype, detail=detail)
        db.session.add(log)
        db.session.commit()

        return jsonify({"counts": session.violation_counts()})

    @app.route("/api/exam/<int:session_id>/submit", methods=["POST"])
    def api_submit_exam(session_id):
        session = ExamSession.query.get_or_404(session_id)
        if session.status == "submitted":
            return jsonify({"redirect": url_for("exam_submitted", session_id=session.id)})

        payload = request.get_json(force=True, silent=True) or {}
        answers = payload.get("answers") or {}

        score = 0
        for q in QUESTIONS:
            given = answers.get(str(q["id"]))
            if given == q["answer"]:
                score += 1

        session.score = score
        session.total_questions = len(QUESTIONS)
        session.status = "submitted"
        session.end_time = datetime.utcnow()
        db.session.commit()

        return jsonify({"redirect": url_for("exam_submitted", session_id=session.id)})


app = create_app()

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
