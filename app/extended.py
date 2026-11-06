"""Quản trị người dùng (bước 3.3 sẽ tách thành blueprint/service riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import schemas, services
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("extended", __name__)


@bp.get("/admin/users")
@require_role("ADMIN")
@store_scope
def admin_users() -> Any:
    return jsonify(services.list_users(g.actor))


@bp.patch("/admin/users/<user_id>/role")
@require_role("ADMIN")
@store_scope
def admin_change_role(user_id: str) -> Any:
    role = schemas.parse_role_body(request.get_json(silent=True))
    return jsonify(services.change_role(g.actor, user_id, role))
