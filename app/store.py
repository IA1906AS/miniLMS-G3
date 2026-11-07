import json
import pathlib
import secrets
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import bcrypt
import psycopg
from psycopg import pq as pg_pq

db: dict[str, Any] | None = None


def _in_transaction(connection: Any) -> bool:
    """Tương đương sqlite3 Connection.in_transaction."""
    return connection.info.transaction_status != pg_pq.TransactionStatus.IDLE


def _run_script(connection: Any, script: str) -> None:
    """Tương đương sqlite3.executescript: chạy từng câu lệnh DDL riêng."""
    for statement in script.split(";"):
        if statement.strip():
            connection.execute(statement)


def _table_columns(connection: Any, table: str) -> list[tuple[Any, ...]]:
    """Tương đương PRAGMA table_info: trả các dòng có cột [1] là tên cột."""
    return connection.execute(
        "SELECT ordinal_position, column_name, data_type "
        "FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()


def init(database_url: str, clock: Callable[[], float] | None = None) -> dict[str, Any]:
    global db

    now = clock if clock is not None else time.time
    connection = psycopg.connect(database_url, autocommit=True)
    _run_script(
        connection,
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            bio TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            locked INTEGER NOT NULL DEFAULT 0,
            role TEXT NOT NULL,
            pw_hash BYTEA NOT NULL
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
            created_at DOUBLE PRECISION NOT NULL,
            decided_at DOUBLE PRECISION,
            decided_by TEXT
        );
        CREATE TABLE IF NOT EXISTS enrollments (
            course_id TEXT NOT NULL REFERENCES courses(id),
            student_id TEXT NOT NULL REFERENCES users(id),
            score DOUBLE PRECISION NOT NULL,
            PRIMARY KEY (course_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL REFERENCES users(id),
            expires_at DOUBLE PRECISION NOT NULL,
            used_at DOUBLE PRECISION
        );
        CREATE TABLE IF NOT EXISTS oauth_accounts (
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (provider, subject)
        );
        CREATE TABLE IF NOT EXISTS outbox_events (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at DOUBLE PRECISION NOT NULL,
            locked_until DOUBLE PRECISION,
            created_at DOUBLE PRECISION NOT NULL,
            sent_at DOUBLE PRECISION,
            last_error TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_outbox_due
            ON outbox_events (status, next_attempt_at);
        CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            due_at DOUBLE PRECISION NOT NULL,
            created_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            assignment_id TEXT NOT NULL REFERENCES assignments(id),
            student_id TEXT NOT NULL REFERENCES users(id),
            content TEXT NOT NULL,
            submitted_at DOUBLE PRECISION NOT NULL,
            UNIQUE (assignment_id, student_id)
        );
        CREATE TABLE IF NOT EXISTS announcements (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id),
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id),
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL REFERENCES threads(id),
            body TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id),
            title TEXT NOT NULL,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            created_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quizzes (
            id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL REFERENCES courses(id),
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            duration_minutes INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            created_at DOUBLE PRECISION NOT NULL
        );
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id TEXT PRIMARY KEY,
            quiz_id TEXT NOT NULL REFERENCES quizzes(id),
            question_text TEXT NOT NULL,
            options TEXT NOT NULL,
            correct_option INTEGER NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            points DOUBLE PRECISION NOT NULL DEFAULT 1.0
        );
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id TEXT PRIMARY KEY,
            quiz_id TEXT NOT NULL REFERENCES quizzes(id),
            student_id TEXT NOT NULL REFERENCES users(id),
            attempt_number INTEGER NOT NULL,
            started_at DOUBLE PRECISION NOT NULL,
            submitted_at DOUBLE PRECISION,
            score DOUBLE PRECISION,
            answers TEXT
        );
        """,
    )
    columns = {row[1] for row in _table_columns(connection, "users")}
    if "bio" not in columns:  # DB cũ tạo trước khi có cột bio
        connection.execute("ALTER TABLE users ADD COLUMN bio TEXT NOT NULL DEFAULT ''")
    if "phone" not in columns:  # DB cũ tạo trước khi có cột phone
        connection.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
    if "locked" not in columns:  # DB cũ tạo trước khi có cờ khoá
        connection.execute("ALTER TABLE users ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    if "avatar_path" not in columns:
        connection.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT NOT NULL DEFAULT ''")
    sub_cols = {row[1] for row in _table_columns(connection, "submissions")}
    if "file_name" not in sub_cols:
        connection.execute("ALTER TABLE submissions ADD COLUMN file_name TEXT NOT NULL DEFAULT ''")
    if "file_path" not in sub_cols:
        connection.execute("ALTER TABLE submissions ADD COLUMN file_path TEXT NOT NULL DEFAULT ''")
    if "grade" not in sub_cols:
        connection.execute("ALTER TABLE submissions ADD COLUMN grade DOUBLE PRECISION")
    if "feedback" not in sub_cols:
        connection.execute("ALTER TABLE submissions ADD COLUMN feedback TEXT NOT NULL DEFAULT ''")
    if "graded_by" not in sub_cols:
        connection.execute("ALTER TABLE submissions ADD COLUMN graded_by TEXT")
    question_cols = {row[1] for row in _table_columns(connection, "quiz_questions")}
    if "position" not in question_cols:
        connection.execute(
            "ALTER TABLE quiz_questions ADD COLUMN position INTEGER NOT NULL DEFAULT 0"
        )
    if "graded_at" not in sub_cols:
        connection.execute("ALTER TABLE submissions ADD COLUMN graded_at DOUBLE PRECISION")
    seed = json.loads((pathlib.Path(__file__).parent / "seed.json").read_text(encoding="utf-8"))
    with connection.transaction():
        for user_data in seed["users"]:
            connection.execute(
                """
                INSERT INTO users (id, email, name, role, pw_hash)
                VALUES (%s, %s, '', %s, %s)
                ON CONFLICT DO NOTHING
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
                INSERT INTO courses (id, name, instructor_id)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (course["id"], course["name"], course["instructorId"]),
            )
        for enrollment in seed["enrollments"]:
            connection.execute(
                """
                INSERT INTO enrollments (course_id, student_id, score)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
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
    phones = {row[0]: row[1] for row in connection.execute("SELECT id, phone FROM users")}
    avatars = {row[0]: row[1] for row in connection.execute("SELECT id, avatar_path FROM users")}
    locked = {row[0]: bool(row[1]) for row in connection.execute("SELECT id, locked FROM users")}
    db = {
        "users": users,
        "by_email": {user["email"].lower(): user for user in users.values()},
        "courses": courses,
        "enrollments": enrollments,
        "bios": bios,
        "phones": phones,
        "avatars": avatars,
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
        if "phones" not in state:
            state["phones"] = {}
        state["phones"].clear()
        state["phones"].update(
            {row[0]: row[1] for row in connection.execute("SELECT id, phone FROM users")}
        )
        if "avatars" not in state:
            state["avatars"] = {}
        state["avatars"].clear()
        state["avatars"].update(
            {row[0]: row[1] for row in connection.execute("SELECT id, avatar_path FROM users")}
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
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    user["id"],
                    user["email"],
                    user["name"],
                    user["role"],
                    user["pw_hash"],
                ),
            )
        except psycopg.IntegrityError as error:
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
        connection.execute("BEGIN")
        try:
            row = connection.execute(
                """
                SELECT users.id, users.email, users.name, users.role, users.pw_hash
                FROM oauth_accounts
                JOIN users ON users.id = oauth_accounts.user_id
                WHERE oauth_accounts.provider = %s AND oauth_accounts.subject = %s
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
                "SELECT 1 FROM users WHERE lower(email) = lower(%s)", (email,)
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
                VALUES (%s, %s, %s, %s, %s)
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
                VALUES (%s, %s, %s)
                """,
                (provider, subject, user["id"]),
            )
            connection.execute("COMMIT")
        except ValueError:
            raise
        except psycopg.IntegrityError as error:
            if _in_transaction(connection):
                connection.execute("ROLLBACK")
            raise ValueError("OAuth account could not be linked") from error
        except psycopg.Error:
            if _in_transaction(connection):
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
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                UPDATE password_reset_tokens
                SET used_at = %s
                WHERE user_id = %s AND used_at IS NULL
                """,
                (expires_at, user_id),
            )
            connection.execute(
                """
                INSERT INTO password_reset_tokens (token_hash, user_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (token_hash, user_id, expires_at),
            )
            connection.execute("COMMIT")
        except (psycopg.Error, TypeError, ValueError):
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
        connection.execute("BEGIN")
        try:
            row = connection.execute(
                """
                SELECT user_id FROM password_reset_tokens
                WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s
                """,
                (token_hash, now),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return False
            user_id = row[0]
            password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10))
            connection.execute(
                "UPDATE users SET pw_hash = %s WHERE id = %s",
                (password_hash, user_id),
            )
            connection.execute(
                "UPDATE password_reset_tokens SET used_at = %s WHERE token_hash = %s",
                (now, token_hash),
            )
            connection.execute("COMMIT")
        except (psycopg.Error, TypeError, ValueError):
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
                WHERE token_hash = %s AND used_at IS NULL AND expires_at > %s
                """,
                (token_hash, now),
            )
            .fetchone()
            is not None
        )


def update_grade(
    state: dict[str, Any], course_id: str, student_id: str, score: int | float
) -> None:
    """Ghi đè điểm vô điều kiện (last-write-wins) — bản Before, chưa có optimistic locking."""
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                "UPDATE enrollments SET score = %s WHERE course_id = %s AND student_id = %s",
                (score, course_id, student_id),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        state["enrollments"][(course_id, student_id)] = score


def recover_expired_outbox(state: dict[str, Any], now: float) -> int:
    """Return crashed claims (SENDING past their lease) to the PENDING pool."""
    with state["lock"]:
        cursor = state["connection"].execute(
            """
            UPDATE outbox_events
               SET status = 'PENDING', locked_until = NULL
             WHERE status = 'SENDING'
               AND locked_until IS NOT NULL
               AND locked_until <= %s
            """,
            (now,),
        )
        return cursor.rowcount


def claim_outbox_batch(
    state: dict[str, Any], now: float, limit: int, lease_seconds: float
) -> list[dict[str, Any]]:
    """Atomically move due events to SENDING and return them.

    The SELECT and the UPDATE share one BEGIN transaction, so a second
    worker (in this process or another one) cannot claim the same rows.
    """
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            rows = connection.execute(
                """
                SELECT id, event_id, type, payload, attempts
                  FROM outbox_events
                 WHERE status = 'PENDING' AND next_attempt_at <= %s
                 ORDER BY id
                 LIMIT %s
                """,
                (now, limit),
            ).fetchall()
            if rows:
                connection.cursor().executemany(
                    """
                    UPDATE outbox_events SET status = 'SENDING', locked_until = %s
                     WHERE id = %s AND status = 'PENDING'
                    """,
                    [(now + lease_seconds, row[0]) for row in rows],
                )
            connection.execute("COMMIT")
        except psycopg.Error:
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
               SET status = 'SENT', sent_at = %s, locked_until = NULL, last_error = NULL
             WHERE event_id = %s
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
        connection.execute("BEGIN")
        try:
            row = connection.execute(
                "SELECT attempts FROM outbox_events WHERE event_id = %s",
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
                   SET status = %s, attempts = %s, next_attempt_at = %s,
                       locked_until = NULL, last_error = %s
                 WHERE event_id = %s
                """,
                (status, attempts, now + retry_delay, error, event_id),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
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
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO enrollments (course_id, student_id, score)
                VALUES (%s, %s, 0.0)
                """,
                (course_id, student_id),
            )
            connection.execute("COMMIT")
        except psycopg.IntegrityError as error:
            connection.execute("ROLLBACK")
            raise ValueError("Enrollment already exists") from error
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        state["enrollments"][(course_id, student_id)] = 0.0


def remove_enrollment(state: dict[str, Any], course_id: str, student_id: str) -> bool:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            cursor = connection.execute(
                "DELETE FROM enrollments WHERE course_id = %s AND student_id = %s",
                (course_id, student_id),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        removed = cursor.rowcount > 0
        if removed:
            state["enrollments"].pop((course_id, student_id), None)
        return removed


def set_user_role(state: dict[str, Any], user_id: str, role: str) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        user = state["users"].get(user_id)
        if user is not None:
            user["role"] = role


def count_users_with_role(state: dict[str, Any], role: str) -> int:
    with state["lock"]:
        row = (
            state["connection"]
            .execute("SELECT COUNT(*) FROM users WHERE role = %s", (role,))
            .fetchone()
        )
    return int(row[0]) if row is not None else 0


def set_user_profile(
    state: dict[str, Any],
    user_id: str,
    *,
    name: str | None = None,
    bio: str | None = None,
    phone: str | None = None,
) -> None:
    assignments: list[str] = []
    params: list[Any] = []
    if name is not None:
        assignments.append("name = %s")
        params.append(name)
    if bio is not None:
        assignments.append("bio = %s")
        params.append(bio)
    if phone is not None:
        assignments.append("phone = %s")
        params.append(phone)
    if not assignments:
        return
    params.append(user_id)

    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(f"UPDATE users SET {', '.join(assignments)} WHERE id = %s", params)
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        user = state["users"].get(user_id)
        if user is not None and name is not None:
            user["name"] = name
        if bio is not None:
            state["bios"][user_id] = bio
        if phone is not None:
            state.setdefault("phones", {})[user_id] = phone


def update_password_hash(state: dict[str, Any], user_id: str, password_hash: bytes) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                "UPDATE users SET pw_hash = %s WHERE id = %s", (password_hash, user_id)
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        user = state["users"].get(user_id)
        if user is not None:
            user["pw_hash"] = password_hash


def set_user_locked(state: dict[str, Any], user_id: str, locked: bool) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                "UPDATE users SET locked = %s WHERE id = %s", (1 if locked else 0, user_id)
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        state["locked"][user_id] = locked


def create_course(state: dict[str, Any], *, name: str, instructor_id: str) -> dict[str, Any]:
    course = {"id": "c_" + uuid.uuid4().hex, "name": name, "instructorId": instructor_id}
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                "INSERT INTO courses (id, name, instructor_id) VALUES (%s, %s, %s)",
                (course["id"], course["name"], course["instructorId"]),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        state["courses"][course["id"]] = course
    return course


def update_course(state: dict[str, Any], course_id: str, name: str) -> dict[str, Any] | None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            cursor = connection.execute(
                "UPDATE courses SET name = %s WHERE id = %s", (name, course_id)
            )
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                return None
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        if course_id in state["courses"]:
            state["courses"][course_id]["name"] = name
        return state["courses"].get(course_id)


def delete_course(state: dict[str, Any], course_id: str) -> bool:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                "DELETE FROM comments WHERE thread_id IN"
                " (SELECT id FROM threads WHERE course_id = %s)",
                (course_id,),
            )
            connection.execute("DELETE FROM threads WHERE course_id = %s", (course_id,))
            connection.execute(
                "DELETE FROM submissions WHERE assignment_id IN"
                " (SELECT id FROM assignments WHERE course_id = %s)",
                (course_id,),
            )
            connection.execute("DELETE FROM assignments WHERE course_id = %s", (course_id,))
            connection.execute("DELETE FROM announcements WHERE course_id = %s", (course_id,))
            connection.execute("DELETE FROM enrollments WHERE course_id = %s", (course_id,))
            cursor = connection.execute("DELETE FROM courses WHERE id = %s", (course_id,))
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                return False
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        state["courses"].pop(course_id, None)
        to_delete = [key for key in state["enrollments"] if key[0] == course_id]
        for key in to_delete:
            state["enrollments"].pop(key, None)
        return True


def list_course_members(state: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        course = state["courses"].get(course_id)
        if course is None:
            return []
        instructor_id = course["instructorId"]
        student_ids = [sid for (cid, sid) in state["enrollments"] if cid == course_id]
        all_ids = [instructor_id] + [sid for sid in student_ids if sid != instructor_id]
        members = []
        for uid in all_ids:
            u = state["users"].get(uid)
            if u:
                members.append(
                    {
                        "id": u["id"],
                        "email": u["email"],
                        "name": u.get("name", ""),
                        "role": u["role"],
                        "bio": state.get("bios", {}).get(uid, ""),
                        "phone": state.get("phones", {}).get(uid, ""),
                    }
                )
        return members


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
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO course_requests (id, name, instructor_id, status, created_at)
                VALUES (%s, %s, %s, 'PENDING', %s)
                """,
                (request["id"], name, instructor_id, now),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
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
                  FROM course_requests WHERE instructor_id = %s ORDER BY created_at
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
              FROM course_requests WHERE id = %s
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
        connection.execute("BEGIN")
        try:
            cursor = connection.execute(
                """
                UPDATE course_requests
                   SET status = 'APPROVED', decided_at = %s, decided_by = %s
                 WHERE id = %s AND status = 'PENDING'
                """,
                (now, decided_by, request_id),
            )
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                return False
            connection.execute(
                "INSERT INTO courses (id, name, instructor_id) VALUES (%s, %s, %s)",
                (course["id"], course["name"], course["instructorId"]),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
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
               SET status = 'REJECTED', decided_at = %s, decided_by = %s
             WHERE id = %s AND status = 'PENDING'
            """,
            (now, decided_by, request_id),
        )
        return cursor.rowcount > 0


def _assignment_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "courseId": row[1],
        "title": row[2],
        "description": row[3],
        "dueAt": row[4],
        "createdBy": row[5],
        "createdAt": row[6],
    }


def _submission_view(row: tuple[Any, ...]) -> dict[str, Any]:
    view: dict[str, Any] = {
        "id": row[0],
        "assignmentId": row[1],
        "studentId": row[2],
        "content": row[3],
        "submittedAt": row[4],
    }
    if len(row) > 5 and row[5]:
        view["fileName"] = row[5]
    if len(row) > 6 and row[6]:
        view["filePath"] = row[6]
    if len(row) > 7 and row[7] is not None:
        view["grade"] = row[7]
    if len(row) > 8 and row[8]:
        view["feedback"] = row[8]
    if len(row) > 9 and row[9]:
        view["gradedBy"] = row[9]
    if len(row) > 10 and row[10] is not None:
        view["gradedAt"] = row[10]
    return view


def create_assignment(
    state: dict[str, Any],
    *,
    course_id: str,
    title: str,
    description: str,
    due_at: float,
    created_by: str,
    now: float,
) -> dict[str, Any]:
    assignment = {
        "id": "a_" + uuid.uuid4().hex,
        "courseId": course_id,
        "title": title,
        "description": description,
        "dueAt": due_at,
        "createdBy": created_by,
        "createdAt": now,
    }
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO assignments
                    (id, course_id, title, description, due_at, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    assignment["id"],
                    course_id,
                    title,
                    description,
                    due_at,
                    created_by,
                    now,
                ),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return assignment


def get_assignment(state: dict[str, Any], assignment_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, description, due_at, created_by, created_at
              FROM assignments WHERE id = %s
            """,
                (assignment_id,),
            )
            .fetchone()
        )
    return _assignment_view(row) if row is not None else None


def list_assignments(state: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, description, due_at, created_by, created_at
              FROM assignments WHERE course_id = %s ORDER BY created_at
            """,
                (course_id,),
            )
            .fetchall()
        )
    return [_assignment_view(row) for row in rows]


def create_submission(
    state: dict[str, Any],
    *,
    assignment_id: str,
    student_id: str,
    content: str,
    now: float,
    file_name: str = "",
    file_path: str = "",
) -> tuple[str, dict[str, Any] | None]:
    """Trả ('created'|'unchanged'|'conflict', submission)."""
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            row = connection.execute(
                """
                SELECT id, assignment_id, student_id, content, submitted_at,
                       file_name, file_path, grade, feedback, graded_by, graded_at
                  FROM submissions WHERE assignment_id = %s AND student_id = %s
                """,
                (assignment_id, student_id),
            ).fetchone()
            if row is not None:
                connection.execute("COMMIT")
                if row[3] == content and (not file_name or row[5] == file_name):
                    return "unchanged", _submission_view(row)
                return "conflict", None

            submission: dict[str, Any] = {
                "id": "s_" + uuid.uuid4().hex,
                "assignmentId": assignment_id,
                "studentId": student_id,
                "content": content,
                "submittedAt": now,
            }
            if file_name:
                submission["fileName"] = file_name
            if file_path:
                submission["filePath"] = file_path
            connection.execute(
                """
                INSERT INTO submissions
                    (id, assignment_id, student_id, content, submitted_at, file_name, file_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    submission["id"],
                    assignment_id,
                    student_id,
                    content,
                    now,
                    file_name,
                    file_path,
                ),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return "created", submission


def get_submission(
    state: dict[str, Any], assignment_id: str, student_id: str
) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, assignment_id, student_id, content, submitted_at,
                   file_name, file_path, grade, feedback, graded_by, graded_at
              FROM submissions WHERE assignment_id = %s AND student_id = %s
            """,
                (assignment_id, student_id),
            )
            .fetchone()
        )
    return _submission_view(row) if row is not None else None


def list_submissions(state: dict[str, Any], assignment_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, assignment_id, student_id, content, submitted_at,
                   file_name, file_path, grade, feedback, graded_by, graded_at
              FROM submissions WHERE assignment_id = %s ORDER BY submitted_at
            """,
                (assignment_id,),
            )
            .fetchall()
        )
    return [_submission_view(row) for row in rows]


def list_student_submissions(state: dict[str, Any], student_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, assignment_id, student_id, content, submitted_at,
                   file_name, file_path, grade, feedback, graded_by, graded_at
              FROM submissions WHERE student_id = %s ORDER BY submitted_at
            """,
                (student_id,),
            )
            .fetchall()
        )
    return [_submission_view(row) for row in rows]


def get_submission_by_id(state: dict[str, Any], submission_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, assignment_id, student_id, content, submitted_at,
                   file_name, file_path, grade, feedback, graded_by, graded_at
              FROM submissions WHERE id = %s
            """,
                (submission_id,),
            )
            .fetchone()
        )
    return _submission_view(row) if row is not None else None


def grade_submission(
    state: dict[str, Any],
    *,
    submission_id: str,
    grade: float,
    feedback: str,
    graded_by: str,
    now: float,
) -> dict[str, Any] | None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            cursor = connection.execute(
                """
                UPDATE submissions
                   SET grade = %s, feedback = %s, graded_by = %s, graded_at = %s
                 WHERE id = %s
                """,
                (grade, feedback, graded_by, now, submission_id),
            )
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                return None
            row = connection.execute(
                """
                SELECT id, assignment_id, student_id, content, submitted_at,
                       file_name, file_path, grade, feedback, graded_by, graded_at
                  FROM submissions WHERE id = %s
                """,
                (submission_id,),
            ).fetchone()
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        return _submission_view(row) if row is not None else None


def _announcement_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "courseId": row[1],
        "title": row[2],
        "body": row[3],
        "createdBy": row[4],
        "createdAt": row[5],
    }


def _thread_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "courseId": row[1],
        "title": row[2],
        "body": row[3],
        "createdBy": row[4],
        "createdAt": row[5],
    }


def _comment_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "threadId": row[1],
        "body": row[2],
        "createdBy": row[3],
        "createdAt": row[4],
    }


def create_announcement(
    state: dict[str, Any],
    *,
    course_id: str,
    title: str,
    body: str,
    created_by: str,
    now: float,
) -> dict[str, Any]:
    announcement = {
        "id": "an_" + uuid.uuid4().hex,
        "courseId": course_id,
        "title": title,
        "body": body,
        "createdBy": created_by,
        "createdAt": now,
    }
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO announcements
                    (id, course_id, title, body, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    announcement["id"],
                    course_id,
                    title,
                    body,
                    created_by,
                    now,
                ),
            )
            # Sinh outbox events gửi email thông báo tới toàn bộ sinh viên đã ghi danh
            students = connection.execute(
                """
                SELECT u.email, u.name
                  FROM enrollments e
                  JOIN users u ON e.student_id = u.id
                 WHERE e.course_id = %s
                """,
                (course_id,),
            ).fetchall()
            for student in students:
                event_id = secrets.token_urlsafe(16)
                student_name = student[1] or "bạn"
                payload = json.dumps(
                    {
                        "to": student[0],
                        "subject": f"Thông báo mới: {title}",
                        "body": f"Chào {student_name},\n\nThông báo từ khoá học:\n\n{body}\n",
                        "courseId": course_id,
                    },
                    ensure_ascii=False,
                )
                connection.execute(
                    """
                    INSERT INTO outbox_events (
                        event_id, type, payload, status, attempts,
                        next_attempt_at, created_at
                    )
                    VALUES (%s, 'announcement.posted', %s, 'PENDING', 0, %s, %s)
                    """,
                    (event_id, payload, now, now),
                )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return announcement


def list_announcements(state: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, body, created_by, created_at
              FROM announcements WHERE course_id = %s ORDER BY created_at
            """,
                (course_id,),
            )
            .fetchall()
        )
    return [_announcement_view(row) for row in rows]


def get_announcement(state: dict[str, Any], announcement_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, body, created_by, created_at
              FROM announcements WHERE id = %s
            """,
                (announcement_id,),
            )
            .fetchone()
        )
    return _announcement_view(row) if row is not None else None


def delete_announcement(state: dict[str, Any], announcement_id: str) -> bool:
    with state["lock"]:
        cursor = state["connection"].execute(
            "DELETE FROM announcements WHERE id = %s", (announcement_id,)
        )
        return cursor.rowcount > 0


def create_thread(
    state: dict[str, Any],
    *,
    course_id: str,
    title: str,
    body: str,
    created_by: str,
    now: float,
) -> dict[str, Any]:
    thread = {
        "id": "th_" + uuid.uuid4().hex,
        "courseId": course_id,
        "title": title,
        "body": body,
        "createdBy": created_by,
        "createdAt": now,
    }
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO threads (id, course_id, title, body, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (thread["id"], course_id, title, body, created_by, now),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return thread


def list_threads(state: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, body, created_by, created_at
              FROM threads WHERE course_id = %s ORDER BY created_at
            """,
                (course_id,),
            )
            .fetchall()
        )
    return [_thread_view(row) for row in rows]


def get_thread(state: dict[str, Any], thread_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, body, created_by, created_at
              FROM threads WHERE id = %s
            """,
                (thread_id,),
            )
            .fetchone()
        )
    return _thread_view(row) if row is not None else None


def delete_thread(state: dict[str, Any], thread_id: str) -> bool:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute("DELETE FROM comments WHERE thread_id = %s", (thread_id,))
            cursor = connection.execute("DELETE FROM threads WHERE id = %s", (thread_id,))
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        return cursor.rowcount > 0


def create_comment(
    state: dict[str, Any], *, thread_id: str, body: str, created_by: str, now: float
) -> dict[str, Any]:
    comment = {
        "id": "cm_" + uuid.uuid4().hex,
        "threadId": thread_id,
        "body": body,
        "createdBy": created_by,
        "createdAt": now,
    }
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO comments (id, thread_id, body, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (comment["id"], thread_id, body, created_by, now),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return comment


def list_comments(state: dict[str, Any], thread_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, thread_id, body, created_by, created_at
              FROM comments WHERE thread_id = %s ORDER BY created_at
            """,
                (thread_id,),
            )
            .fetchall()
        )
    return [_comment_view(row) for row in rows]


def get_comment(state: dict[str, Any], comment_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, thread_id, body, created_by, created_at
              FROM comments WHERE id = %s
            """,
                (comment_id,),
            )
            .fetchone()
        )
    return _comment_view(row) if row is not None else None


def delete_comment(state: dict[str, Any], comment_id: str) -> bool:
    with state["lock"]:
        cursor = state["connection"].execute("DELETE FROM comments WHERE id = %s", (comment_id,))
        return cursor.rowcount > 0


# --- Materials & Storage --------------------------------------------------


def _material_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "courseId": row[1],
        "title": row[2],
        "fileName": row[3],
        "filePath": row[4],
        "fileSize": row[5],
        "createdBy": row[6],
        "createdAt": row[7],
    }


def create_material(
    state: dict[str, Any],
    *,
    course_id: str,
    title: str,
    file_name: str,
    file_path: str,
    file_size: int,
    created_by: str,
    now: float,
) -> dict[str, Any]:
    material = {
        "id": "mat_" + uuid.uuid4().hex,
        "courseId": course_id,
        "title": title,
        "fileName": file_name,
        "filePath": file_path,
        "fileSize": file_size,
        "createdBy": created_by,
        "createdAt": now,
    }
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO materials
                    (id, course_id, title, file_name, file_path, file_size, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    material["id"],
                    course_id,
                    title,
                    file_name,
                    file_path,
                    file_size,
                    created_by,
                    now,
                ),
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return material


def list_materials(state: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, file_name, file_path, file_size, created_by, created_at
              FROM materials WHERE course_id = %s ORDER BY created_at
            """,
                (course_id,),
            )
            .fetchall()
        )
    return [_material_view(row) for row in rows]


def get_material(state: dict[str, Any], material_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, file_name, file_path, file_size, created_by, created_at
              FROM materials WHERE id = %s
            """,
                (material_id,),
            )
            .fetchone()
        )
    return _material_view(row) if row is not None else None


def delete_material(state: dict[str, Any], material_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            row = connection.execute(
                """
                SELECT id, course_id, title, file_name, file_path, file_size, created_by, created_at
                  FROM materials WHERE id = %s
                """,
                (material_id,),
            ).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                return None
            connection.execute("DELETE FROM materials WHERE id = %s", (material_id,))
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return _material_view(row)


def set_user_avatar(state: dict[str, Any], user_id: str, avatar_path: str) -> None:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                "UPDATE users SET avatar_path = %s WHERE id = %s", (avatar_path, user_id)
            )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        state.setdefault("avatars", {})[user_id] = avatar_path


def get_user_avatar(state: dict[str, Any], user_id: str) -> str:
    with state["lock"]:
        return state.get("avatars", {}).get(user_id, "")


# --- Quizzes & Automatic Grading ------------------------------------------


def _quiz_view(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "id": row[0],
        "courseId": row[1],
        "title": row[2],
        "description": row[3],
        "durationMinutes": row[4],
        "maxAttempts": row[5],
        "createdBy": row[6],
        "createdAt": row[7],
    }


def create_quiz(
    state: dict[str, Any],
    *,
    course_id: str,
    title: str,
    description: str,
    duration_minutes: int,
    max_attempts: int,
    questions: list[dict[str, Any]],
    created_by: str,
    now: float,
) -> dict[str, Any]:
    quiz_id = "qz_" + uuid.uuid4().hex
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute(
                """
                INSERT INTO quizzes
                    (id, course_id, title, description, duration_minutes,
                     max_attempts, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    quiz_id,
                    course_id,
                    title,
                    description,
                    duration_minutes,
                    max_attempts,
                    created_by,
                    now,
                ),
            )
            for position, q in enumerate(questions):
                q_id = "qq_" + uuid.uuid4().hex
                connection.execute(
                    """
                    INSERT INTO quiz_questions
                        (id, quiz_id, question_text, options, correct_option, position, points)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        q_id,
                        quiz_id,
                        q["question"],
                        json.dumps(q["options"], ensure_ascii=False),
                        int(q["correctOption"]),
                        position,
                        float(q.get("points", 1.0)),
                    ),
                )
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
    return get_quiz(state, quiz_id, include_answers=True) or {}


def list_quizzes(state: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    with state["lock"]:
        rows = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, description, duration_minutes,
                   max_attempts, created_by, created_at
              FROM quizzes WHERE course_id = %s ORDER BY created_at
            """,
                (course_id,),
            )
            .fetchall()
        )
    return [_quiz_view(row) for row in rows]


def get_quiz(
    state: dict[str, Any], quiz_id: str, *, include_answers: bool = False
) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, course_id, title, description, duration_minutes,
                   max_attempts, created_by, created_at
              FROM quizzes WHERE id = %s
            """,
                (quiz_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        quiz = _quiz_view(row)
        q_rows = (
            state["connection"]
            .execute(
                """
            SELECT id, question_text, options, correct_option, points
              FROM quiz_questions WHERE quiz_id = %s ORDER BY position
            """,
                (quiz_id,),
            )
            .fetchall()
        )
        questions = []
        for qr in q_rows:
            q_data: dict[str, Any] = {
                "id": qr[0],
                "question": qr[1],
                "options": json.loads(qr[2]),
                "points": qr[4],
            }
            if include_answers:
                q_data["correctOption"] = qr[3]
            questions.append(q_data)
        quiz["questions"] = questions
        return quiz


def delete_quiz(state: dict[str, Any], quiz_id: str) -> bool:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            connection.execute("DELETE FROM quiz_attempts WHERE quiz_id = %s", (quiz_id,))
            connection.execute("DELETE FROM quiz_questions WHERE quiz_id = %s", (quiz_id,))
            cursor = connection.execute("DELETE FROM quizzes WHERE id = %s", (quiz_id,))
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                return False
            connection.execute("COMMIT")
        except psycopg.Error:
            connection.execute("ROLLBACK")
            raise
        return True


def create_quiz_attempt(
    state: dict[str, Any], *, quiz_id: str, student_id: str, now: float
) -> dict[str, Any]:
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            quiz_row = connection.execute(
                "SELECT max_attempts, duration_minutes FROM quizzes WHERE id = %s", (quiz_id,)
            ).fetchone()
            if quiz_row is None:
                connection.execute("ROLLBACK")
                raise ValueError("Quiz not found")
            max_attempts, duration_minutes = quiz_row[0], quiz_row[1]

            # Kiểm tra attempt dở dang
            active = connection.execute(
                """
                SELECT id, started_at FROM quiz_attempts
                 WHERE quiz_id = %s AND student_id = %s AND submitted_at IS NULL
                """,
                (quiz_id, student_id),
            ).fetchone()
            if active is not None:
                connection.execute("COMMIT")
                return {
                    "id": active[0],
                    "quizId": quiz_id,
                    "studentId": student_id,
                    "startedAt": active[1],
                    "durationMinutes": duration_minutes,
                }

            count = connection.execute(
                "SELECT COUNT(*) FROM quiz_attempts WHERE quiz_id = %s AND student_id = %s",
                (quiz_id, student_id),
            ).fetchone()[0]
            if count >= max_attempts:
                connection.execute("ROLLBACK")
                raise ValueError("Max attempts reached")

            attempt_id = "qa_" + uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO quiz_attempts
                    (id, quiz_id, student_id, attempt_number, started_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (attempt_id, quiz_id, student_id, count + 1, now),
            )
            connection.execute("COMMIT")
        except (psycopg.Error, ValueError):
            if _in_transaction(connection):
                connection.execute("ROLLBACK")
            raise
    return {
        "id": attempt_id,
        "quizId": quiz_id,
        "studentId": student_id,
        "attemptNumber": count + 1,
        "startedAt": now,
        "durationMinutes": duration_minutes,
    }


def get_quiz_attempt(state: dict[str, Any], attempt_id: str) -> dict[str, Any] | None:
    with state["lock"]:
        row = (
            state["connection"]
            .execute(
                """
            SELECT id, quiz_id, student_id, attempt_number, started_at,
                   submitted_at, score, answers
              FROM quiz_attempts WHERE id = %s
            """,
                (attempt_id,),
            )
            .fetchone()
        )
        if row is None:
            return None
        return {
            "id": row[0],
            "quizId": row[1],
            "studentId": row[2],
            "attemptNumber": row[3],
            "startedAt": row[4],
            "submittedAt": row[5],
            "score": row[6],
            "answers": json.loads(row[7]) if row[7] else {},
        }


def submit_quiz_attempt(
    state: dict[str, Any], *, attempt_id: str, answers: dict[str, int], now: float
) -> dict[str, Any]:
    """Đối chiếu đáp án và tự động chấm điểm hoàn toàn trên server."""
    with state["lock"]:
        connection = state["connection"]
        connection.execute("BEGIN")
        try:
            attempt_row = connection.execute(
                """
                SELECT id, quiz_id, student_id, started_at, submitted_at
                  FROM quiz_attempts WHERE id = %s
                """,
                (attempt_id,),
            ).fetchone()
            if attempt_row is None:
                connection.execute("ROLLBACK")
                raise ValueError("Attempt not found")
            if attempt_row[4] is not None:
                connection.execute("ROLLBACK")
                raise ValueError("Already submitted")

            quiz_id = attempt_row[1]
            questions = connection.execute(
                "SELECT id, correct_option, points FROM quiz_questions WHERE quiz_id = %s",
                (quiz_id,),
            ).fetchall()

            total_points = 0.0
            earned_points = 0.0
            for q_id, correct_opt, pts in questions:
                total_points += float(pts)
                chosen = answers.get(q_id)
                if chosen is not None and int(chosen) == int(correct_opt):
                    earned_points += float(pts)

            final_score = (
                round((earned_points / total_points) * 10.0, 2) if total_points > 0 else 0.0
            )

            connection.execute(
                """
                UPDATE quiz_attempts
                   SET submitted_at = %s, score = %s, answers = %s
                 WHERE id = %s
                """,
                (now, final_score, json.dumps(answers), attempt_id),
            )
            connection.execute("COMMIT")
        except (psycopg.Error, ValueError):
            if _in_transaction(connection):
                connection.execute("ROLLBACK")
            raise
    return {
        "attemptId": attempt_id,
        "quizId": quiz_id,
        "score": final_score,
        "maxScore": 10.0,
        "submittedAt": now,
    }


def list_quiz_attempts(
    state: dict[str, Any], quiz_id: str, *, student_id: str | None = None
) -> list[dict[str, Any]]:
    with state["lock"]:
        if student_id:
            rows = (
                state["connection"]
                .execute(
                    """
                SELECT id, quiz_id, student_id, attempt_number, started_at,
                       submitted_at, score, answers
                  FROM quiz_attempts WHERE quiz_id = %s AND student_id = %s ORDER BY started_at
                """,
                    (quiz_id, student_id),
                )
                .fetchall()
            )
        else:
            rows = (
                state["connection"]
                .execute(
                    """
                SELECT id, quiz_id, student_id, attempt_number, started_at,
                       submitted_at, score, answers
                  FROM quiz_attempts WHERE quiz_id = %s ORDER BY started_at
                """,
                    (quiz_id,),
                )
                .fetchall()
            )
        return [
            {
                "id": r[0],
                "quizId": r[1],
                "studentId": r[2],
                "attemptNumber": r[3],
                "startedAt": r[4],
                "submittedAt": r[5],
                "score": r[6],
            }
            for r in rows
        ]
