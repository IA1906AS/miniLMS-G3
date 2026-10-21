import json
import pathlib
import secrets
import sqlite3
import threading
from typing import Any

import bcrypt


db: dict[str, Any] | None = None


def init(database_path: str = "lms.sqlite3") -> dict[str, Any]:
    global db

    connection = sqlite3.connect(
        database_path, check_same_thread=False, isolation_level=None
    )
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL,
            pw_hash BLOB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS courses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            instructor_id TEXT NOT NULL
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
        """
    )
    seed = json.loads(
        (pathlib.Path(__file__).parent / "seed.json").read_text(encoding="utf-8")
    )
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
                    bcrypt.hashpw(
                        user_data["password"].encode("utf-8"), bcrypt.gensalt(rounds=10)
                    ),
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
        for row in connection.execute(
            "SELECT id, name, instructor_id FROM courses"
        )
    }
    enrollments = {
        (row[0], row[1]): row[2]
        for row in connection.execute(
            "SELECT course_id, student_id, score FROM enrollments"
        )
    }
    db = {
        "users": users,
        "by_email": {user["email"].lower(): user for user in users.values()},
        "courses": courses,
        "enrollments": enrollments,
        "attempts": {},
        "dummy_pw_hash": bcrypt.hashpw(
            b"not-a-real-account-password", bcrypt.gensalt(rounds=10)
        ),
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
        state["by_email"].update(
            {user["email"].lower(): user for user in users.values()}
        )
        state["courses"].clear()
        state["courses"].update(
            {
                row[0]: {"id": row[0], "name": row[1], "instructorId": row[2]}
                for row in connection.execute(
                    "SELECT id, name, instructor_id FROM courses"
                )
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
            password_hash = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt(rounds=10)
            )
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


def password_reset_is_valid(
    state: dict[str, Any], token_hash: str, now: float
) -> bool:
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
