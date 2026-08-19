"""Database models for the Smart Exam Proctoring app."""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Student(db.Model):
    __tablename__ = "students"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    face_sample_count = db.Column(db.Integer, default=0)

    sessions = db.relationship(
        "ExamSession", backref="student", cascade="all, delete-orphan"
    )

    @property
    def is_enrolled(self):
        """Whether enough face samples exist to run identity verification."""
        return self.face_sample_count >= 3


class ExamSession(db.Model):
    __tablename__ = "exam_sessions"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    status = db.Column(db.String(20), default="in_progress")  # in_progress|submitted|expired
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    end_time = db.Column(db.DateTime, nullable=True)
    score = db.Column(db.Integer, nullable=True)
    total_questions = db.Column(db.Integer, default=0)

    violations = db.relationship(
        "ViolationLog", backref="session", cascade="all, delete-orphan",
        order_by="ViolationLog.timestamp",
    )

    def violation_counts(self):
        counts = {}
        for v in self.violations:
            counts[v.type] = counts.get(v.type, 0) + 1
        return counts

    def duration_seconds(self):
        end = self.end_time or datetime.utcnow()
        return int((end - self.start_time).total_seconds())


class ViolationLog(db.Model):
    __tablename__ = "violation_logs"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("exam_sessions.id"), nullable=False)
    type = db.Column(db.String(40), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    detail = db.Column(db.String(255), nullable=True)
    snapshot_path = db.Column(db.String(255), nullable=True)  # relative to /static


VIOLATION_LABELS = {
    "no_face": "Face not visible",
    "multiple_faces": "Multiple people detected",
    "identity_mismatch": "Identity mismatch",
    "tab_switch": "Switched tabs",
    "window_blur": "Left exam window",
    "audio_spike": "Excess background noise",
}

VIOLATION_SEVERITY = {
    "no_face": "warn",
    "multiple_faces": "flag",
    "identity_mismatch": "flag",
    "tab_switch": "flag",
    "window_blur": "warn",
    "audio_spike": "warn",
}
