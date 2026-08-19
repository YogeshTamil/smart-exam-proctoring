# Invigil — Smart Exam Proctoring

A browser-based exam proctoring prototype. Students enroll their face,
sit a timed exam, and a Flask + OpenCV backend watches for the things that
usually matter to an invigilator: is a face visible, is it the right person,
is the room quiet, and is the browser tab actually the exam.

## Features

- **Face enrollment** — capture a handful of reference photos per student
  through the browser; an OpenCV LBPH recognizer trains on them.
- **Live proctoring during the exam**
  - *Identity verification* — periodic webcam frames are matched against the
    enrolled recognizer.
  - *No-face / multiple-faces detection* — flags an empty seat or a second
    person in frame.
  - *Tab-switch & window-blur detection* — flags leaving the exam tab/window.
  - *Background noise monitoring* — flags sustained loud audio via the
    browser's Web Audio API.
- **Evidence trail** — every visual violation saves a snapshot; every
  violation (visual or behavioral) is timestamped and logged per session.
- **Admin dashboard** — a ledger of all sessions with scores and flag counts,
  and a per-session timeline with evidence thumbnails.
- **A working sample exam** — 5 MCQs with auto-grading, so the proctoring
  logic has something real to sit alongside.

## Architecture

```
Browser (student)                Flask backend                 Storage
─────────────────                ─────────────                 ───────
getUserMedia (video+audio)
  │
  ├─ frame every 4s ─────POST /api/proctor/frame──▶ OpenCV Haar cascade
  │                                                 + LBPH recognizer ──▶ SQLite (violation_logs)
  │                                                                   └─▶ static/violations/*.jpg
  ├─ Web Audio RMS ──────POST /api/proctor/event───▶ throttle + log ────▶ SQLite
  ├─ visibilitychange/blur
  └─ submit answers ─────POST /api/exam/<id>/submit▶ auto-grade ────────▶ SQLite (exam_sessions)

Admin browser ── GET /dashboard, /dashboard/session/<id> ── reads SQLite + snapshots
```

Everything runs on one machine — there's no external API calls, no cloud
biometrics service, and no telemetry. All face data, video frames, and
audio levels are processed locally and never leave the Flask process.

## Setup

Requires Python 3.10+.

```bash
cd smart-exam-proctoring
python3 -m venv venv && source venv/bin/activate   # optional but recommended
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. The camera/microphone prompts require
either `localhost`/`127.0.0.1` or HTTPS — if you deploy this beyond your own
machine, put it behind TLS or the browser will refuse to grant camera access.

A SQLite database and face-model files are created automatically under
`instance/` on first run.

## Using it

1. **Register** — go to *Register*, enter a name, capture at least 3
   photos (keep one face centered in frame), and submit. You're redirected
   straight into the exam.
2. **Take the exam** — the camera badge in the header turns green when a
   verified single face is visible and red when something's flagged; a
   countdown ring tracks the 10-minute timer. Violations pop up as toasts
   and are all logged in the background.
3. **Review** — open *Dashboard* to see every session, its score, and its
   flag count. Click into a session for the full timeline with snapshots.

## Tuning

These constants are deliberately conservative starting points — recognition
accuracy and audio levels depend heavily on your webcam, microphone, and
room, so expect to adjust them:

| Setting | Where | Default | Effect |
|---|---|---|---|
| `IDENTITY_CONFIDENCE_THRESHOLD` | `proctor.py` | `75` | LBPH is a *distance* score — lower is a better match. Raise this if enrolled students are being flagged as mismatches; lower it if mismatches aren't being caught. |
| `AUDIO_THRESHOLD` | `static/js/exam.js` | `0.09` | RMS level (0–1) above which a frame counts as "loud." |
| `FRAME_INTERVAL_MS` | `static/js/exam.js` | `4000` | How often a frame is sent for face analysis. |
| Minimum face samples | `models.py` (`Student.is_enrolled`) | `3` | More samples generally improve recognition accuracy. |

## Project structure

```
smart-exam-proctoring/
├── app.py              Flask routes + API endpoints
├── models.py            SQLAlchemy models (Student, ExamSession, ViolationLog)
├── proctor.py           OpenCV: face detection, LBPH training/inference, snapshots
├── questions.py          Sample question bank + exam duration
├── requirements.txt
├── templates/            Jinja2 pages (roster, register, exam, dashboard, ...)
└── static/
    ├── css/               Design system (tokens) + page styles
    └── js/                register.js (enrollment) + exam.js (live proctoring)
```

## Limitations & responsible use

This is a working prototype, not a compliance-ready product. Before using
it with real students, you'd want to add at minimum:

- **Authentication & authorization** — right now anyone can open `/dashboard`
  or start an exam as any registered student; there's no login system.
- **Informed consent** — biometric monitoring of students is regulated in
  many places (e.g. FERPA and state biometric-privacy laws in the US, GDPR
  in the EU). Get explicit consent and a clear retention/deletion policy for
  face data and snapshots before deploying this for real.
- **Accessibility & accommodations** — camera/audio-based proctoring can
  disadvantage students with disabilities, unstable internet, or shared
  living spaces. Have a human-review and appeals process for flags, not just
  an automated score.
- **HTTPS in production** — required for camera/mic access outside localhost,
  and for protecting video frames and violation data in transit.
- **A real question bank** — `questions.py` is a hardcoded demo list; swap it
  for a database-backed bank if you need multiple exams or randomization.

## Ideas for extending

- Multiple exams / question banks selectable at exam start.
- Per-student login instead of picking from an open roster.
- WebSocket-based frame streaming instead of polling, for lower latency.
- A "review & override" action on the dashboard so a human can dismiss a
  false-positive flag.
