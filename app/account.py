"""Bước 3.1 — endpoint phiên và tài khoản (blueprint riêng).

Gate (lớp 2) đã bắt buộc Bearer; ở đây không có route công khai nào nên không cần
allowlist. Kiểm tra dữ liệu ở `schemas` (lớp 5), nghiệp vụ ở `account_service` (lớp 4).
"""

import os
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, send_file

from . import account_service, schemas
from .errors import NotFound, ValidationError
from .scoped import store_scope

bp = Blueprint("account", __name__)


def _avatar_upload_dir() -> str:
    folder = current_app.config.get("AVATAR_FOLDER")
    if not folder:
        folder = os.path.join(current_app.root_path, "..", "data", "uploads", "avatars")
    return os.path.abspath(folder)


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


@bp.post("/users/me/avatar")
@store_scope
def upload_avatar() -> Any:
    file = request.files.get("avatar")
    if not file or not file.filename:
        raise ValidationError()
    return (
        jsonify(
            account_service.update_avatar(g.actor, file.read(), file.filename, _avatar_upload_dir())
        ),
        200,
    )


@bp.get("/users/<user_id>/avatar")
@store_scope
def get_avatar(user_id: str) -> Any:
    path = account_service.get_avatar_path(user_id, _avatar_upload_dir())
    if not path:
        raise NotFound()
    return send_file(path)
