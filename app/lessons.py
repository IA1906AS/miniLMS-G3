"""Endpoint bài học và tiến độ học (blueprint riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import lesson_service, schemas
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("lessons", __name__)


@bp.get("/courses/<course_id>/lessons")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_lessons(course_id: str) -> Any:
    return jsonify(lesson_service.list_lessons(g.actor, course_id))


@bp.post("/courses/<course_id>/lessons")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def create_lesson(course_id: str) -> Any:
    title, body, video_url, is_preview = schemas.parse_lesson_body(request.get_json(silent=True))
    return (
        jsonify(
            lesson_service.create_lesson(g.actor, course_id, title, body, video_url, is_preview)
        ),
        201,
    )


@bp.get("/lessons/<lesson_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def get_lesson(lesson_id: str) -> Any:
    return jsonify(lesson_service.get_lesson(g.actor, lesson_id))


@bp.patch("/lessons/<lesson_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def update_lesson(lesson_id: str) -> Any:
    title, body, video_url, is_preview = schemas.parse_lesson_body(request.get_json(silent=True))
    return jsonify(
        lesson_service.update_lesson(g.actor, lesson_id, title, body, video_url, is_preview)
    )


@bp.delete("/lessons/<lesson_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def delete_lesson(lesson_id: str) -> Any:
    return jsonify(lesson_service.delete_lesson(g.actor, lesson_id))


@bp.post("/lessons/<lesson_id>/complete")
@require_role("STUDENT")
@store_scope
def complete_lesson(lesson_id: str) -> Any:
    return jsonify(lesson_service.complete_lesson(g.actor, lesson_id))


@bp.get("/courses/<course_id>/progress")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def course_progress(course_id: str) -> Any:
    return jsonify(lesson_service.course_progress(g.actor, course_id))
