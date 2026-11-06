"""Bước 3.1 — endpoint phiên và tài khoản (blueprint riêng).

Gate (lớp 2) đã bắt buộc Bearer; ở đây không có route công khai nào nên không cần
allowlist. Kiểm tra dữ liệu ở `schemas` (lớp 5), nghiệp vụ ở `account_service` (lớp 4).
"""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import account_service, schemas
from .scoped import store_scope

bp = Blueprint("account", __name__)


@bp.post("/auth/logout")
@store_scope
def logout() -> Any:
    return jsonify(account_service.logout(g.actor))


@bp.post("/me/password")
@store_scope
def change_password() -> Any:
    old_password, new_password = schemas.parse_password_change_body(request.get_json(silent=True))
    return jsonify(account_service.change_password(g.actor, old_password, new_password))


@bp.get("/users/me")
@store_scope
def get_profile() -> Any:
    return jsonify(account_service.get_profile(g.actor))


@bp.put("/users/me")
@store_scope
def update_profile() -> Any:
    updates = schemas.parse_profile_update_body(request.get_json(silent=True))
    return jsonify(account_service.update_profile(g.actor, updates))
