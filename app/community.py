"""Endpoint cộng đồng: tin nhắn, live session, bình luận bài học."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import community_service
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("community", __name__)


@bp.get("/messages")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def conversations() -> Any:
    return jsonify(community_service.conversations(g.actor))


@bp.get("/messages/<user_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def thread(user_id: str) -> Any:
    return jsonify(community_service.thread(g.actor, user_id))


@bp.post("/messages/<user_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def send_message(user_id: str) -> Any:
    body = str((request.get_json(silent=True) or {}).get("body") or "")
    return jsonify(community_service.send_message(g.actor, user_id, body)), 201


@bp.get("/courses/<course_id>/live")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_live(course_id: str) -> Any:
    return jsonify(community_service.list_live_sessions(g.actor, course_id))


@bp.post("/courses/<course_id>/live")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def create_live(course_id: str) -> Any:
    payload = request.get_json(silent=True) or {}
    return (
        jsonify(
            community_service.create_live_session(
                g.actor,
                course_id,
                str(payload.get("title") or ""),
                str(payload.get("url") or ""),
                float(payload.get("startsAt") or 0),
            )
        ),
        201,
    )


@bp.delete("/live/<session_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def delete_live(session_id: str) -> Any:
    return jsonify(community_service.delete_live_session(g.actor, session_id))


@bp.get("/lessons/<lesson_id>/comments")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_comments(lesson_id: str) -> Any:
    return jsonify(community_service.list_lesson_comments(g.actor, lesson_id))


@bp.post("/lessons/<lesson_id>/comments")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def add_comment(lesson_id: str) -> Any:
    body = str((request.get_json(silent=True) or {}).get("body") or "")
    return jsonify(community_service.add_lesson_comment(g.actor, lesson_id, body)), 201


@bp.delete("/lesson-comments/<comment_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def delete_comment(comment_id: str) -> Any:
    return jsonify(community_service.delete_lesson_comment(g.actor, comment_id))
