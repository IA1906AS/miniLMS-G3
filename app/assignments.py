"""Bước 3.4 — endpoint bài tập và nộp bài (blueprint riêng)."""

import os
from typing import Any

from flask import Blueprint, current_app, g, jsonify, request, send_file

from . import assignment_service, schemas, storage
from .errors import ValidationError
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("assignments", __name__)


def _submission_upload_dir() -> str:
    folder = current_app.config.get("SUBMISSION_FOLDER")
    if not folder:
        folder = os.path.join(current_app.root_path, "..", "data", "uploads", "submissions")
    return os.path.abspath(folder)


@bp.post("/courses/<course_id>/assignments")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def create_assignment(course_id: str) -> Any:
    assignment_service.authorize_manage(g.actor, course_id)
    title, description, due_at = schemas.parse_assignment_body(request.get_json(silent=True))
    return (
        jsonify(
            assignment_service.create_assignment(g.actor, course_id, title, description, due_at)
        ),
        201,
    )


@bp.get("/courses/<course_id>/assignments")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_assignments(course_id: str) -> Any:
    return jsonify(assignment_service.list_assignments(g.actor, course_id))


@bp.post("/assignments/<assignment_id>/submissions")
@require_role("STUDENT")
@store_scope
def submit(assignment_id: str) -> Any:
    assignment_service.authorize_submit(g.actor, assignment_id)
    file = request.files.get("file")
    stored_name = ""
    clean_name = ""
    if file and file.filename:
        stored_name, clean_name, _ = storage.secure_save_file(
            file.read(),
            file.filename,
            _submission_upload_dir(),
            allowed_extensions=storage.ALLOWED_SUBMISSION_EXTENSIONS,
            max_bytes=storage.MAX_SUBMISSION_BYTES,
        )

    json_body = request.get_json(silent=True)
    if json_body is not None:
        content = schemas.parse_submission_body(json_body)
    elif request.form.get("content"):
        content = request.form["content"].strip()
    elif clean_name:
        content = f"Uploaded file: {clean_name}"
    else:
        raise ValidationError()

    submission, created = assignment_service.submit(
        g.actor,
        assignment_id,
        content,
        file_name=clean_name,
        file_path=stored_name,
    )
    return jsonify(submission), 201 if created else 200


@bp.post("/submissions/<submission_id>/grade")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def grade_submission(submission_id: str) -> Any:
    grade, feedback = schemas.parse_grade_submission_body(request.get_json(silent=True))
    return jsonify(assignment_service.grade_submission(g.actor, submission_id, grade, feedback))


@bp.get("/submissions/<submission_id>/download")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def download_submission(submission_id: str) -> Any:
    filepath, filename = assignment_service.get_submission_file(
        g.actor, submission_id, _submission_upload_dir()
    )
    return send_file(filepath, download_name=filename, as_attachment=True)


@bp.get("/assignments/<assignment_id>/submissions")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_submissions(assignment_id: str) -> Any:
    return jsonify(assignment_service.list_submissions(g.actor, assignment_id))


@bp.get("/me/submissions")
@require_role("STUDENT")
@store_scope
def my_submissions() -> Any:
    return jsonify(assignment_service.my_submissions(g.actor))
