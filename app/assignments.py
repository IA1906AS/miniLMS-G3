"""Bước 3.4 — endpoint bài tập và nộp bài (blueprint riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import assignment_service, schemas
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("assignments", __name__)


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
    content = schemas.parse_submission_body(request.get_json(silent=True))
    submission, created = assignment_service.submit(g.actor, assignment_id, content)
    return jsonify(submission), 201 if created else 200


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
