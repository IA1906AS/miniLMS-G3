import json
import pathlib
import threading
from typing import Any

import bcrypt


db: dict[str, Any] | None = None


def init() -> dict[str, Any]:
    global db

    seed = json.loads(
        (pathlib.Path(__file__).parent / "seed.json").read_text(encoding="utf-8")
    )
    users: dict[str, dict[str, Any]] = {}
    for user_data in seed["users"]:
        password_hash = bcrypt.hashpw(
            user_data["password"].encode("utf-8"), bcrypt.gensalt(rounds=10)
        )
        user = {
            "id": user_data["id"],
            "email": user_data["email"],
            "role": user_data["role"],
            "pw_hash": password_hash,
        }
        users[user["id"]] = user

    db = {
        "users": users,
        "by_email": {user["email"].lower(): user for user in users.values()},
        "courses": {course["id"]: dict(course) for course in seed["courses"]},
        "enrollments": {
            (enrollment["courseId"], enrollment["studentId"]): enrollment["score"]
            for enrollment in seed["enrollments"]
        },
        "attempts": {},
        "dummy_pw_hash": bcrypt.hashpw(
            b"not-a-real-account-password", bcrypt.gensalt(rounds=10)
        ),
        "lock": threading.RLock(),
    }
    return db
