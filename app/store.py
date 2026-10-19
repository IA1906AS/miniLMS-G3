"""In-memory state loaded from seed.json. Plaintext passwords are hashed and dropped."""
import json
import threading
from pathlib import Path

from . import auth

DEFAULT_SEED = Path(__file__).resolve().parent.parent / "seed.json"


class Store:
    def __init__(self, data):
        self.lock = threading.RLock()
        self.users = {}
        self._by_email = {}
        for u in data["users"]:
            user = {
                "id": u["id"],
                "email": u["email"].strip().lower(),
                "role": u["role"],
                "password_hash": auth.hash_password(u["password"]),  # plaintext never kept
            }
            self.users[user["id"]] = user
            self._by_email[user["email"]] = user
        self.courses = {c["id"]: dict(c) for c in data["courses"]}
        self.enrollments = [dict(e) for e in data["enrollments"]]
        self.dummy_hash = auth.hash_password("dummy-password-for-timing")
        self.login_attempts = {}  # email -> {"fails": int, "locked_until": float}

    def get_user(self, user_id):
        return self.users.get(user_id) if isinstance(user_id, str) else None

    def find_user_by_email(self, email):
        return self._by_email.get(email)

    @staticmethod
    def public_user(user):
        return {"id": user["id"], "email": user["email"], "role": user["role"]}

    def get_course(self, course_id):
        return self.courses.get(course_id) if isinstance(course_id, str) else None

    def course_enrollments(self, course_id):
        return [e for e in self.enrollments if e["courseId"] == course_id]

    def find_enrollment(self, course_id, student_id):
        for e in self.enrollments:
            if e["courseId"] == course_id and e["studentId"] == student_id:
                return e
        return None


def load(path=None):
    with open(path or DEFAULT_SEED, encoding="utf-8") as f:
        return Store(json.load(f))


_current = None


def set_current(state):
    global _current
    _current = state


def current():
    if _current is None:
        raise RuntimeError("store not initialised; call create_app() first")
    return _current
