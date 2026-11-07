import time
from typing import Any

import bcrypt
import jwt

from . import audit
from . import store as store_module
from .errors import (
    AccountLocked,
    Conflict,
    InvalidCredentials,
    Unauthenticated,
    ValidationError,
)

MAX_FAILS, LOCK_SECONDS = 5, 15 * 60
_DUMMY = bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=10))


def _store(state: dict[str, Any] | None) -> dict[str, Any]:
    current = state if state is not None else store_module.db
    if current is None:
        raise RuntimeError("The LMS store has not been initialized")
    return current


def issue_token(
    user_id: str,
    secret: str,
    ttl: int,
    *,
    now: float | None = None,
) -> str:
    moment = int(time.time() if now is None else now)
    return jwt.encode(
        {"sub": user_id, "iat": moment, "exp": moment + ttl},
        secret,
        algorithm="HS256",
    )


def invalidate_tokens(state: dict[str, Any], user_id: str) -> None:
    """Vô hiệu mọi token phát trước giây hiện tại của user này.

    Mốc lưu theo giây (int): token phát ở đúng giây hiện tại vẫn hợp lệ, token phát
    ở giây trước đó thì không.
    """
    with state["lock"]:
        state["tokens_valid_after"][user_id] = int(state["now"]())


def verify_token(token: str, secret: str, state: dict[str, Any] | None = None) -> dict[str, str]:
    current = _store(state)
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
        if set(payload) != {"sub", "iat", "exp"} or not isinstance(payload["sub"], str):
            raise jwt.InvalidTokenError("Unexpected token claims")
        user = current["users"].get(payload["sub"])
    except (jwt.PyJWTError, TypeError, ValueError) as error:
        raise Unauthenticated() from error

    if user is None:
        raise Unauthenticated()

    valid_after = current["tokens_valid_after"].get(payload["sub"], 0)
    if payload["iat"] < valid_after:
        raise Unauthenticated()
    if current["locked"].get(user["id"]):
        # Tài khoản bị khoá: mọi request mang token cũ đều 401.
        raise Unauthenticated()
    return {"id": user["id"], "email": user["email"], "role": user["role"]}


def _authenticate_user(
    email: str, password: str, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValidationError()

    current = _store(state)
    key = email.strip().lower()
    now = current["now"]()
    with current["lock"]:
        attempt = current["attempts"].setdefault(key, {"fails": 0, "locked_until": 0.0})
        if attempt["locked_until"] > now:
            raise AccountLocked()
        if attempt["locked_until"]:
            attempt.update(fails=0, locked_until=0.0)

        user = current["by_email"].get(key)
        if user is not None and current["locked"].get(user["id"]):
            # Tài khoản bị admin khoá: 429 kể cả khi mật khẩu đúng.
            raise AccountLocked()
        encoded_password = password.encode("utf-8")
        password_hash = user["pw_hash"] if user is not None else _DUMMY
        password_matches = bcrypt.checkpw(encoded_password[:72], password_hash)
        if user is None or len(encoded_password) > 72 or not password_matches:
            attempt["fails"] += 1
            if attempt["fails"] >= MAX_FAILS:
                attempt["locked_until"] = now + LOCK_SECONDS
            raise InvalidCredentials()

        attempt["fails"] = 0
        return user


def login(
    email: str,
    password: str,
    secret: str,
    ttl: int,
    state: dict[str, Any] | None = None,
) -> dict[str, str | int]:
    user = _authenticate_user(email, password, state)
    current = _store(state)
    with current["lock"]:
        token = issue_token(user["id"], secret, ttl, now=current["now"]())
    audit.record(user["id"], "LOGIN", "/auth/login", "OK", path=current.get("audit_log_path"))
    return {
        "accessToken": token,
        "expiresIn": ttl,
    }


def register(
    email: str,
    name: str,
    password: str,
    secret: str,
    ttl: int,
    state: dict[str, Any],
) -> dict[str, str | int | dict[str, str]]:
    if not isinstance(email, str) or not isinstance(name, str) or not isinstance(password, str):
        raise ValidationError()
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10))
    try:
        user = store_module.create_user(state, email=email, name=name, password_hash=password_hash)
    except ValueError as error:
        raise Conflict() from error
    return {
        "accessToken": issue_token(user["id"], secret, ttl),
        "expiresIn": ttl,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"],
        },
    }


def authenticate(email: str, password: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    return _authenticate_user(email, password, state)


def create_access_token(user_id: str, secret: str, ttl_seconds: int) -> str:
    return issue_token(user_id, secret, ttl_seconds)


def verify_access_token(token: str, secret: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
    except jwt.PyJWTError as error:
        raise Unauthenticated() from error
