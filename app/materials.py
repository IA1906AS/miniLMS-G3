"""Endpoint quản lý tài liệu bài giảng (Blueprint riêng)."""

import os
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, send_file

from . import material_service
from .errors import ValidationError
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("materials", __name__)


def _upload_dir() -> str:
    folder = current_app.config.get("UPLOAD_FOLDER")
    if not folder:
        folder = os.path.join(current_app.root_path, "..", "data", "uploads", "materials")
    return os.path.abspath(folder)


@bp.post("/courses/<course_id>/materials")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def upload_material(course_id: str) -> Any:
    title = request.form.get("title") or ""
    file = request.files.get("file")
    if not file or not file.filename:
        raise ValidationError()
    file_bytes = file.read()
    material = material_service.create_material(
        g.actor,
        course_id=course_id,
        title=title,
        file_bytes=file_bytes,
        original_name=file.filename,
        upload_dir=_upload_dir(),
    )
    return jsonify(material), 201


@bp.get("/courses/<course_id>/materials")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_materials(course_id: str) -> Any:
    return jsonify(material_service.list_materials(g.actor, course_id))


@bp.get("/materials/<material_id>/download")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def download_material(material_id: str) -> Any:
    filepath, filename = material_service.get_material_for_download(
        g.actor, material_id, _upload_dir()
    )
    return send_file(filepath, download_name=filename, as_attachment=True)


@bp.delete("/materials/<material_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def delete_material(material_id: str) -> Any:
    return jsonify(material_service.delete_material(g.actor, material_id, _upload_dir()))
