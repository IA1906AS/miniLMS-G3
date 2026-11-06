import json
import pathlib
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import bcrypt

db: dict[str, Any] | None = None


def init(
    database_path: str = "lms.sqlite3", clock: Callable[[], float] | None = None
) -> dict[str, Any]:
    global db

    now = clock if clock is not None else time.time
    connection = sqlite3.connect(database_path, check_same_thread=False, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            locked INTEGER NOT NULL DEFAULT 0,
            role TEXT NOT NULL,
            pw_hash BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            instructor_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS course_requests (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            instructor_id TEXT NOT NULL REFERENCES users(id),
            status TEXT NOT NULL DEFAULT 'PENDING',
            created_at REAL NOT NULL,
            decided_at REAL,
            decided_by TEXT
        );
        CREATE TABLE IF NOT EXISTS enrollments (
            course_id TEXT NOT NULL REFERENCES courses(id),
            student_id TEXT NOT NULL REFERENCES users(id),
            score REAL NOT NULL,
            PRIMARY KEY (course_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            expires_at REAL NOT NULL,
            used_at REAL
        );
        CREATE TABLE IF NOT EXISTS oauth_accounts (
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (provider, subject)
        );
        CREATE TABLE IF NOT EXISTS outbox_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL,
            locked_until REAL,
            created_at REAL NOT NULL,
            sent_at REAL,
            last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_due
            ON outbox_events (status, next_attempt_at);
        """
    )
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if "bio" not in columns:  # DB cũ tạo trước khi có cột bio
        connection.execute("ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''")
    if "locked" not in columns:  # DB cũ tạo trước khi có cờ khoá
        connection.execute("ALTER TABLE users ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    seed = json.loads((pathlib.Path(__file__).parent / "seed.json").read_text(encoding="utf-8"))
    with connection:
        for user_data in seed["users"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO users (id, email, name, role, pw_hash)
                VALUES (?, ?, '', ?, ?)
                """,
                (
                    user_data["id"],
                    user_data["email"],
                    user_data["role"],
                    bcrypt.hashpw(user_data["password"].encode("utf-8"), bcrypt.gensalt(rounds=10)),
                ),
            )
        for course in seed["courses"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO courses (id, name, instructor_id)
                VALUES (?, ?, ?)
                """,
                (course["id"], course["name"], course["instructorId"]),
            )
        for enrollment in seed["enrollments"]:
            connection.execute(
                """
                INSERT OR IGNORE INTO enrollments (course_id, student_id, score)
                VALUES (?, ?, ?)
                """,
                (
                    enrollment["courseId"],
                    enrollment["studentId"],
                    enrollment["score"],
                ),
            )

    users = {}
    for row in connection.execute("SELECT id, email, name, role, pw_hash FROM users"):
        user = {
            "id": row[0],
            "email": row[1],
            "role": row[3],
            "pw_hash": row[4],
        }
        if row[2]:
            user["name"] = row[2]
        users[user["id"]] = user
    courses = {
        row[0]: {"id": row[0], "name": row[1], "instructorId": row[2]}
        for row in connection.execute("SELECT id, name, instructor_id FROM courses")
    }
    enrollments = {
        (row[0], row[1]): row[2]
        for row in connection.execute("SELECT course_id, student_id, score FROM enrollments")
    }
    bios = {row[0]: row[1] for row in connection.execute("SELECT id, bio FROM users")}
    locked = {row[0]: bool(row[1]) for row in connection.execute("SELECT id, locked FROM users")}
    db = {
        "users": users,
        "by_email": {user["email"].lower(): user for user in users.values()},
        "courses": courses,
        "enrollments": enrollments,
        "bios": bios,
        "locked": locked,
        "attempts": {},
        "tokens_valid_after": {},
        "now": now,
        "dummy_pw_hash": bcrypt.hashpw(b"not-a-real-account-password", bcrypt.gensalt(rounds=10)),
        "connection": connection,
        "lock": threading.RLock(),
    }
    return db


def refresh(state: dict[str, Any]) -> None:
    with state["lock"]:
        connection = state["connection"]
        users = {}
        for row in connection.execute("SELECT id, email, name, role, pw_hash FROM users"):
            user = {
                "id": row[0],
                "email": row[1],
                "role": row[3],
                "pw_hash": row[4],
            }
            if row[2]:
                user["name"] = row[2]
            users[user["id"]] = user
        state["users"].clear()
        state["users"].update(users)
        state["by_email"].clear()
        state["by_email"].update({user["email"].lower(): user for user in users.values()})
        state["courses"].clear()
        state["courses"].update(
            {
                row[0]: {"id": row[0], "name": row[1], "instructorId": row[2]}
                for row in connection.execute("SELECT id, name, instructor_id FROM courses")
            }
        )
        state["enrollments"].clear()
        state["enrollments"].update(
            {
                (row[0], row[1]): row[2]
                for row in connection.execute(
                    "SELECT course_id, student_id, score FROM enrollments"
                )
            }
        )
        state["bios"].clear()
        state["bios"].update(
            {row[0]: row[1] for row in connection.execute("SELECT id, bio FROM users")}
        )
        state["locked"].clear()
        state["locked"].update(
            {row[0]: bool(row[1]) for row in connection.execute("SELECT id, locked FROM users")}
        )


def create_user(
    state: dict[str, Any],
    *,
    email: str,
    name: str,
    password_hash: bytes,
) -> dict[str, Any]:
    user = {
        "id": "u_" + secrets.token_urlsafe(12),
        "email": email,
        "name": name,
        "role": "STUDENT",
        "pw_hash": password_hash,
    }
    with state["lock"]:
        try:
            state["connection"].execute(
                """
                INSERT INTO users (id, email, name, role, pw_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    user["email"],
                    user["name"],
                    user["role"],
                    user["pw_hash"],
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ValueError("Email address is already registered") from error
        state["users"][user["id"]] = user
        state["by_email"][email.lower()] = user
        state["bios"][user["id"]] = ""
        state["locked"][user["id"]] = False
    return user


def get_or_create_oauth_user(
    state: dict[str, Any],
    *,
    provider: str,
    subject: str,
    email: str,
    name: str,
) -> dict[str, Any]:
    connection = state["connection"]
    with state["lock"]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                """
                SELECT users.id, users.email, users.name, users.role, users.pw_hash
                FROM oauth_accounts
                JOIN users ON users.id = oauth_accounts.user_id
                WHERE oauth_accounts.provider = ? AND oauth_accounts.subject = ?
                """,
                (provider, subject),
            ).fetchone()
            if row is not None:
                connection.execute("COMMIT")
                user = {
                    "id": row[0],
                    "email": row[1],
                    "role": row[3],
                    "pw_hash": row[4],
                }
                if row[2]:
                    user["name"] = row[2]
                state["users"][user["id"]] = user
                state["by_email"][user["email"].lower()] = user
                return user

            if connection.execute(
                "SELECT 1 FROM users WHERE email = ? COLLATE NOCASE", (email,)
            ).fetchone():
                connection.execute("ROLLBACK")
                raise ValueError("Email is already used by another account")

            user = {
                "id": "u_" + secrets.token_urlsafe(12),
                "email": email,
                "name": name,
                "role": "STUDENT",
                "pw_hash": bcrypt.hashpw(
                    secrets.token_urlsafe(32).encode("ascii"), bcrypt.gensalt(rounds=10)
                ),
            }
            connection.execute(
                """
                INSERT INTO users (id, email, name, role, pw_hash)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    user["email"],
                    user["name"],
                    user["role"],
                    user["pw_hash"],
                ),
            )
            connection.execute(
                """
                INSERT INTO oauth_accounts (provider, subject, user_id)
                VALUES (?, ?, ?)
                """,
                (provider, subject, user["id"]),
            )
            connection.execute("COMMIT")
        except ValueError:
            raise
        except sqlite3.IntegrityError as error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise ValueError("OAuth account could not be linked") from error
        except sqlite3.Error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

        state["users"][user["id"]] = user
        state["by_email"][email.lower()] = user
        state["bios"].setdefault(user["id"], "")
        state["locked"].setdefault(user["id"], False)
        return user


def create_password_reset(
    state: dict[str, Any], user_id: str, token_hash: str, expires_at: float
) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = ?
                WHERE user_id = ? AND used_at IS NULL
                """,
                (expires_at, user_id),
            )
            connection.execute(
                """
                INSERT INTO password_reset_tokens (token_hash, user_id, expires_at)
                VALUES (?, ?, ?)
                """,
                (token_hash, user_id, expires_at),
            )
            connection.execute("COMMIT")
        except (sqlite3.Error, TypeError, ValueError):
            connection.execute("ROLLBACK")
            raise


def consume_password_reset(
    state: dict[str, Any],
    token_hash: str,
    password: str,
    now: float,
) -> bool:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                """
                SELECT user_id FROM password_reset_tokens
                WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return False
            user_id = row[0]
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10))
            connection.execute(
                "UPDATE users SET pw_hash = ? WHERE id = ?",
                (password_hash, user_id),
            )
            connection.execute(
                "UPDATE password_reset_tokens SET used_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
            connection.execute("COMMIT")
        except (sqlite3.Error, TypeError, ValueError):
            connection.execute("ROLLBACK")
            raise
        user = state["users"][user_id]
        user["pw_hash"] = password_hash
        state["attempts"].pop(user["email"].lower(), None)
        return True


def password_reset_is_valid(state: dict[str, Any], token_hash: str, now: float) -> bool:
    with state["lock"]:
        return (
            state["connection"]
            .execute(
                """
                SELECT 1 FROM password_reset_tokens
                WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
                """,
                (token_hash, now),
            )
            .fetchone()
            is not None
        )


def update_grade(
    state: dict[str, Any], course_id: str, student_id: str, score: int | float
) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                UPDATE enrollments SET score = ?
                WHERE course_id = ? AND student_id = ?
                """,
                (score, course_id, student_id),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        state["enrollments"][(course_id, student_id)] = score


def create_enrollment(
    state: dict[str, Any],
    *,
    course_id: str,
    student_id: str,
    event: dict[str, Any],
    now: float,
) -> None:
    """Insert the enrollment and its outbox event in one transaction."""
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO enrollments (course_id, student_id, score)
                VALUES (?, ?, ?)
                """,
                (course_id, student_id, 0.0),
            )
            connection.execute(
                """
                INSERT INTO outbox_events (
                    event_id, type, payload, status, attempts,
                    next_attempt_at, created_at
                )
                VALUES (?, ?, ?, 'PENDING', 0, ?, ?)
                """,
                (
                    event["eventId"],
                    event["type"],
                    json.dumps(event["payload"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            connection.execute("ROLLBACK")
            raise ValueError("Enrollment already exists") from error
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        state["enrollments"][(course_id, student_id)] = 0.0


def recover_expired_outbox(state: dict[str, Any], now: float) -> int:
    """Return crashed claims (SENDING past their lease) to the PENDING pool."""
    with state["lock"]:
        cursor = state["connection"].execute(
            """
            UPDATE outbox_events
               SET status = 'PENDING', locked_until = NULL
             WHERE status = 'SENDING'
               AND locked_until IS NOT NULL
               AND locked_until <= ?
            """,
            (now,),
        )
        return cursor.rowcount


def claim_outbox_batch(
    state: dict[str, Any], now: float, limit: int, lease_seconds: float
) -> list[dict[str, Any]]:
    """Atomically move due events to SENDING and return them.

    The SELECT and the UPDATE share one BEGIN IMMEDIATE transaction, so a second
    worker (in this process or another one) cannot claim the same rows.
    """
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            rows = connection.execute(
                """
                SELECT id, event_id, type, payload, attempts
                  FROM outbox_events
                 WHERE status = 'PENDING' AND next_attempt_at <= ?
                 ORDER BY id
                 LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            if rows:
                connection.executemany(
                    """
                    UPDATE outbox_events SET status = 'SENDING', locked_until = ?
                     WHERE id = ? AND status = 'PENDING'
                    """,
                    [(now + lease_seconds, row[0]) for row in rows],
                )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
    return [
        {
            "eventId": row[1],
            "type": row[2],
            "payload": json.loads(row[3]),
            "attempts": row[4],
        }
        for row in rows
    ]


def mark_outbox_sent(state: dict[str, Any], event_id: str, now: float) -> None:
    with state["lock"]:
        state["connection"].execute(
            """
            UPDATE outbox_events
               SET status = 'SENT', sent_at = ?, locked_until = NULL, last_error = NULL
             WHERE event_id = ?
            """,
            (now, event_id),
        )


def mark_outbox_failed(
    state: dict[str, Any],
    event_id: str,
    now: float,
    error: str,
    max_attempts: int,
    retry_delay: float,
) -> str:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            row = connection.execute(
                "SELECT attempts FROM outbox_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return "MISSING"
            attempts = row[0] + 1
            status = "DEAD" if attempts >= max_attempts else "PENDING"
            connection.execute(
                """
                UPDATE outbox_events
                   SET status = ?, attempts = ?, next_attempt_at = ?,
                       locked_until = NULL, last_error = ?
                 WHERE event_id = ?
                """,
                (status, attempts, now + retry_delay, error, event_id),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        return status


def outbox_counts(state: dict[str, Any]) -> dict[str, int]:
    with state["lock"]:
        return {
            row[0]: row[1]
            for row in state["connection"].execute(
                "SELECT status, COUNT(*) FROM outbox_events GROUP BY status"
            )
        }


def add_enrollment(state: dict[str, Any], course_id: str, student_id: str) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO enrollments (course_id, student_id, score)
                VALUES (?, ?, 0.0)
                """,
                (course_id, student_id),
            )
            connection.execute("COMMIT")
        except sqlite3.IntegrityError as error:
            connection.execute("ROLLBACK")
            raise ValueError("Enrollment already exists") from error
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        state["enrollments"][(course_id, student_id)] = 0.0


def remove_enrollment(state: dict[str, Any], course_id: str, student_id: str) -> bool:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = connection.execute(
                "DELETE FROM enrollments WHERE course_id = ? AND student_id = ?",
                (course_id, student_id),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        removed = cursor.rowcount > 0
        if removed:
            state["enrollments"].pop((course_id, student_id), None)
        return removed


def set_user_role(state: dict[str, Any], user_id: str, role: str) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        user = state["users"].get(user_id)
        if user is not None:
            user["role"] = role


def count_users_with_role(state: dict[str, Any], role: str) -> int:
    with state["lock"]:
        row = (
            state["connection"]
            .execute("SELECT COUNT(*) FROM users WHERE role = ?", (role,))
            .fetchone()
        )
    return int(row[0]) if row is not None else 0


def set_user_profile(
    state: dict[str, Any],
    user_id: str,
    *,
    name: str | None = None,
    bio: str | None = None,
) -> None:
    assignments: list[str] = []
    params: list[Any] = []
    if name is not None:
        assignments.append("name = ?")
        params.append(name)
    if bio is not None:
        assignments.append("bio = ?")
        params.append(bio)
    if not assignments:
        return
    params.append(user_id)

    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(f"UPDATE users SET {', '.join(assignments)} WHERE id = ?", params)
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        user = state["users"].get(user_id)
        if user is not None and name is not None:
            user["name"] = name
        if bio is not None:
            state["bios"][user_id] = bio


def update_password_hash(state: dict[str, Any], user_id: str, password_hash: bytes) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "UPDATE users SET pw_hash = ? WHERE id = ?", (password_hash, user_id)
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        user = state["users"].get(user_id)
        if user is not None:
            user["pw_hash"] = password_hash


def set_user_locked(state: dict[str, Any], user_id: str, locked: bool) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "UPDATE users SET locked = ? WHERE id = ?", (1 if locked else 0, user_id)
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        state["locked"][user_id] = locked


def create_course(state: dict[str, Any], *, name: str, instructor_id: str) -> dict[str, Any]:
    course = {"id": "c_" + uuid.uuid4().hex, "name": name, "instructorId": instructor_id}
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                "INSERT INTO courses (id, name, instructor_id) VALUES (?, ?, ?)",
                (course["id"], course["name"], course["instructorId"]),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        state["courses"][course["id"]] = course
    return course


def create_course_request(
    state: dict[str, Any], *, name: str, instructor_id: str, now: float
) -> dict[str, Any]:
    request = {
        "id": "cr_" + uuid.uuid4().hex,
        "name": name,
        "instructorId": instructor_id,
        "status": "PENDING",
        "createdAt": now,
    }
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute(
                """
                INSERT INTO course_requests (id, name, instructor_id, status, created_at)
                VALUES (?, ?, ?, 'PENDING', ?)
                """,
                (request["id"], name, instructor_id, now),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
    return request


def _request_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "instructorId": row[2],
        "status": row[3],
        "createdAt": row[4],
        "decidedAt": row[5],
        "decidedBy": row[6],
    }


def list_course_requests(
    state: dict[str, Any], *, instructor_id: str | None = None
) -> list[dict[str, Any]]:
    with state["lock"]:
        if instructor_id is None:
            rows = (
                state["connection"]
                .execute(
                    """
                SELECT id, name, instructor_id, status, created_at, decided_at, decided_by
                  FROM course_requests ORDER BY created_at
                """
                )
                .fetchall()
            )
        else:
            rows = (
                state["connection"]
                .execute(
                    """
                SELECT id, name, instructor_id, status, created_at, decided_at, decided_by
                  FROM course_requests WHERE instructor_id = ? ORDER BY created_at
                """,
                    (instructor_id,),
                )
                .fetchall()
            )
    return [_request_view(row) for row in rows]


def get_course_request(state: dict[str, Any], request_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, name, instructor_id, status, created_at, decided_at, decided_by
              FROM course_requests WHERE id = ?
            """,
                (request_id,),
            )
            .fetchone()
        )
    return _request_view(row) if row is not None else None


def approve_course_request(
    state: dict[str, Any],
    *,
    request_id: str,
    course: dict[str, Any],
    decided_by: str,
    now: float,
) -> bool:
    """Tạo môn và đóng yêu cầu trong cùng một transaction."""
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = connection.execute(
                """
                UPDATE course_requests
                   SET status = 'APPROVED', decided_at = ?, decided_by = ?
                 WHERE id = ? AND status = 'PENDING'
                """,
                (now, decided_by, request_id),
            )
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                return False
            connection.execute(
                "INSERT INTO courses (id, name, instructor_id) VALUES (?, ?, ?)",
                (course["id"], course["name"], course["instructorId"]),
            )
            connection.execute("COMMIT")
        except sqlite3.Error:
            connection.execute("ROLLBACK")
            raise
        state["courses"][course["id"]] = course
    return True


def reject_course_request(
    state: dict[str, Any], *, request_id: str, decided_by: str, now: float
) -> bool:
    with state["lock"]:
        cursor = state["connection"].execute(
            """
            UPDATE course_requests
               SET status = 'REJECTED', decided_at = ?, decided_by = ?
             WHERE id = ? AND status = 'PENDING'
            """,
            (now, decided_by, request_id),
        )
        return cursor.rowcount > 0
