"""Bước 3.1 — nghiệp vụ phiên và tài khoản.

Không import Flask: mọi kiểm tra quyền/dữ liệu nằm ở đây để gọi trực tiếp vẫn an toàn.
"""

from typing import Any

import bcrypt

from . import audit, auth, schemas
from . import store as store_module
from .errors import InvalidCredentials, Unauthenticated, ValidationError
from .runtime import current_store


def _profile(state: dict[str, Any], user: dict[str, Any]) -> dict[str, str]:
    return {
        "id": user["id"],
        "email": user["email"],
        "fullName": user.get("name", ""),
        "bio": state["bios"].get(user["id"], ""),
        "role": user["role"],
    }


def _actor_user(state: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    user = state["users"].get(actor.get("id"))
    if user is None:
        raise Unauthenticated()
    return user


def get_profile(actor: dict[str, Any]) -> dict[str, str]:
    state = current_store()
    with state["lock"]:
        return _profile(state, _actor_user(state, actor))


def update_profile(actor: dict[str, Any], updates: dict[str, str]) -> dict[str, str]:
    state = current_store()
    with state["lock"]:
        user = _actor_user(state, actor)
        store_module.set_user_profile(
            state,
            user["id"],
            name=updates.get("fullName"),
            bio=updates.get("bio"),
            phone=updates.get("phone"),
        )
        audit.record(
            user["id"],
            "PROFILE_UPDATE",
            "/users/me",
            "OK",
            fields=sorted(updates),
            path=state["audit_log_path"],
        )
        return _profile(state, state["users"][user["id"]])


def change_password(actor: dict[str, Any], old_password: str, new_password: str) -> dict[str, str]:
    state = current_store()
    with state["lock"]:
        user = _actor_user(state, actor)
        encoded_old = old_password.encode("utf-8")
        if len(encoded_old) > 72 or not bcrypt.checkpw(encoded_old[:72], user["pw_hash"]):
            # Sai mật khẩu cũ: 401 INVALID_CREDENTIALS (không phải 400).
            raise InvalidCredentials()
        if bcrypt.checkpw(new_password.encode("utf-8"), user["pw_hash"]):
            # Mật khẩu mới trùng mật khẩu cũ.
            raise ValidationError()
        if not schemas.validate_new_password(new_password):
            raise ValidationError()

        password_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=10))
        store_module.update_password_hash(state, user["id"], password_hash)
        auth.invalidate_tokens(state, user["id"])
        audit.record(
            user["id"],
            "PASSWORD_CHANGE",
            "/me/password",
            "OK",
            path=state["audit_log_path"],
        )
        return {"message": "Password updated"}


def logout(actor: dict[str, Any]) -> dict[str, str]:
    state = current_store()
    auth.invalidate_tokens(state, str(actor.get("id")))
    audit.record(
        actor.get("id"),
        "LOGOUT",
        "/auth/logout",
        "OK",
        path=state["audit_log_path"],
    )
    return {"message": "Logged out"}


def update_avatar(
    actor: dict[str, Any], file_bytes: bytes, original_name: str, upload_dir: str
) -> dict[str, str]:
    from . import storage

    state = current_store()
    with state["lock"]:
        user = _actor_user(state, actor)
        stored_name, _, _ = storage.secure_save_file(
            file_bytes,
            original_name,
            upload_dir,
            allowed_extensions=storage.ALLOWED_AVATAR_EXTENSIONS,
            max_bytes=storage.MAX_AVATAR_BYTES,
        )
        store_module.set_user_avatar(state, user["id"], stored_name)
        audit.record(
            user["id"],
            "AVATAR_UPDATE",
            "/users/me/avatar",
            "OK",
            path=state["audit_log_path"],
        )
        return {"avatar": stored_name}


def get_avatar_path(user_id: str, upload_dir: str) -> str | None:
    from . import storage

    state = current_store()
    with state["lock"]:
        avatar_name = store_module.get_user_avatar(state, user_id)
        if not avatar_name:
            return None
        return storage.resolve_file_path(upload_dir, avatar_name)
