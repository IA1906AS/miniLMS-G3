import time
from typing import Any

import bcrypt
import jwt

from . import store as store_module
from .errors import (
    AccountLocked,
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


def issue_token(user_id: str, secret: str, ttl: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + ttl},
        secret,
        algorithm="HS256",
    )


def verify_token(
    token: str, secret: str, state: dict[str, Any] | None = None
) -> dict[str, str]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp"]},
        )
        if set(payload) != {"sub", "iat", "exp"} or not isinstance(
            payload["sub"], str
        ):
            raise jwt.InvalidTokenError("Unexpected token claims")
        user = _store(state)["users"].get(payload["sub"])
    except (jwt.PyJWTError, TypeError, ValueError) as error:
        raise Unauthenticated() from error

    if user is None:
        raise Unauthenticated()
    return {"id": user["id"], "email": user["email"], "role": user["role"]}


def _authenticate_user(
    email: str, password: str, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValidationError()

    current = _store(state)
    key = email.strip().lower()
    now = time.time()
    with current["lock"]:
        attempt = current["attempts"].setdefault(
            key, {"fails": 0, "locked_until": 0.0}
        )
        if attempt["locked_until"] > now:
            raise AccountLocked()
        if attempt["locked_until"]:
            attempt.update(fails=0, locked_until=0.0)

        user = current["by_email"].get(key)
        encoded_password = password.encode("utf-8")
        password_hash = user["pw_hash"] if user is not None else _DUMMY
        password_matches = bcrypt.checkpw(encoded_password[:72], password_hash)
        if (
            user is None
            or len(encoded_password) > 72
            or not password_matches
        ):
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
    return {
        "accessToken": issue_token(user["id"], secret, ttl),
        "expiresIn": ttl,
    }


def authenticate(
    email: str, password: str, state: dict[str, Any] | None = None
) -> dict[str, Any]:
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
