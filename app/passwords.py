import hashlib
import secrets
import time
from typing import Any
from urllib.parse import quote

from flask import url_for

from . import emailer, store


RESET_TOKEN_TTL_SECONDS = 30 * 60


def request_password_reset(
    email: str, state: dict[str, Any], config: dict[str, Any]
) -> None:
    user = state["by_email"].get(email.strip().lower())
    if user is None:
        return

    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = time.time() + RESET_TOKEN_TTL_SECONDS
    store.create_password_reset(state, user["id"], token_hash, expires_at)
    reset_path = (
        url_for("web.password_reset_form") + "?token=" + quote(token, safe="")
    )
    reset_url = f"{config['PUBLIC_BASE_URL'].rstrip('/')}{reset_path}"
    emailer.send_password_reset_email(config, user["email"], reset_url)


def reset_password(token: str, password: str, state: dict[str, Any]) -> bool:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return store.consume_password_reset(
        state, token_hash, password, time.time()
    )


def is_reset_token_valid(token: str, state: dict[str, Any]) -> bool:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return store.password_reset_is_valid(state, token_hash, time.time())
