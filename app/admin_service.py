"""Bước 3.3 — quản trị người dùng, khoá tài khoản và đọc audit.

Không import Flask.
"""

import json
from typing import Any

from . import audit, auth
from . import store as store_module
from .errors import Conflict, Forbidden, NotFound, ValidationError
from .runtime import current_store


def _role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def _require_admin(actor: dict[str, Any]) -> None:
    if _role(actor) != "ADMIN":
        raise Forbidden()


def _user_view(state: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user["role"],
        "locked": state["locked"].get(user["id"], False),
    }


def list_users(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        _require_admin(actor)
        return [_user_view(state, user) for user in state["users"].values()]


def change_role(actor: dict[str, Any], user_id: str, role: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        _require_admin(actor)
        target = state["users"].get(user_id)
        if target is None:
            raise NotFound()
        if target["role"] == "ADMIN" and role != "ADMIN":
            if store_module.count_users_with_role(state, "ADMIN") <= 1:
                raise ValidationError()
            if user_id == actor.get("id"):
                raise ValidationError()

        old_role = target["role"]
        store_module.set_user_role(state, user_id, role)
        auth.invalidate_tokens(state, user_id)
        audit.record(
            actor["id"],
            "ROLE_CHANGE",
            f"/admin/users/{user_id}/role",
            "OK",
            oldRole=old_role,
            newRole=role,
            path=state["audit_log_path"],
        )
        return _user_view(state, target)


def set_locked(actor: dict[str, Any], user_id: str, locked: bool) -> dict[str, Any]:
    state = current_store()
    action = "USER_LOCK" if locked else "USER_UNLOCK"
    with state["lock"]:
        _require_admin(actor)
        target = state["users"].get(user_id)
        if target is None:
            raise NotFound()
        if locked:
            if user_id == actor.get("id"):
                raise ValidationError()
            if (
                target["role"] == "ADMIN"
                and store_module.count_users_with_role(state, "ADMIN") <= 1
            ):
                raise ValidationError()
        if state["locked"].get(user_id, False) == locked:
            raise Conflict()

        store_module.set_user_locked(state, user_id, locked)
        auth.invalidate_tokens(state, user_id)
        audit.record(
            actor["id"],
            action,
            f"/admin/users/{user_id}/{'lock' if locked else 'unlock'}",
            "OK",
            targetId=user_id,
            path=state["audit_log_path"],
        )
        return _user_view(state, target)


def read_audit(actor: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    state = current_store()
    _require_admin(actor)
    try:
        with open(state["audit_log_path"], encoding="utf-8") as audit_file:
            lines = [line for line in audit_file.read().splitlines() if line.strip()]
    except FileNotFoundError:
        return []

    entries: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
