"""Bước 3.3 — endpoint quản trị người dùng (blueprint riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import admin_service, schemas
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("admin", __name__)


@bp.get("/admin/users")
@require_role("ADMIN")
@store_scope
def admin_users() -> Any:
    return jsonify(admin_service.list_users(g.actor))


@bp.patch("/admin/users/<user_id>/role")
@require_role("ADMIN")
@store_scope
def admin_change_role(user_id: str) -> Any:
    role = schemas.parse_role_body(request.get_json(silent=True))
    return jsonify(admin_service.change_role(g.actor, user_id, role))


@bp.post("/admin/users/<user_id>/lock")
@require_role("ADMIN")
@store_scope
def admin_lock_user(user_id: str) -> Any:
    return jsonify(admin_service.set_locked(g.actor, user_id, True))


@bp.post("/admin/users/<user_id>/unlock")
@require_role("ADMIN")
@store_scope
def admin_unlock_user(user_id: str) -> Any:
    return jsonify(admin_service.set_locked(g.actor, user_id, False))


@bp.get("/admin/audit")
@require_role("ADMIN")
@store_scope
def admin_audit() -> Any:
    limit = schemas.parse_audit_limit(request.args.get("limit"))
    return jsonify(admin_service.read_audit(g.actor, limit))
