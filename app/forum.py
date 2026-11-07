"""Bước 3.5 — endpoint thông báo, thảo luận và bình luận (blueprint riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import forum_service, schemas
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("forum", __name__)


@bp.post("/courses/<course_id>/announcements")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def create_announcement(course_id: str) -> Any:
    forum_service.authorize_manage(g.actor, course_id)
    title, body = schemas.parse_announcement_body(request.get_json(silent=True))
    return jsonify(forum_service.create_announcement(g.actor, course_id, title, body)), 201


@bp.get("/courses/<course_id>/announcements")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_announcements(course_id: str) -> Any:
    return jsonify(forum_service.list_announcements(g.actor, course_id))


@bp.delete("/announcements/<announcement_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def delete_announcement(announcement_id: str) -> Any:
    return jsonify(forum_service.delete_announcement(g.actor, announcement_id))


@bp.post("/courses/<course_id>/threads")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def create_thread(course_id: str) -> Any:
    forum_service.authorize_view(g.actor, course_id)
    title, body = schemas.parse_thread_body(request.get_json(silent=True))
    return jsonify(forum_service.create_thread(g.actor, course_id, title, body)), 201


@bp.get("/courses/<course_id>/threads")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_threads(course_id: str) -> Any:
    return jsonify(forum_service.list_threads(g.actor, course_id))


@bp.patch("/threads/<thread_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def update_thread(thread_id: str) -> Any:
    title, body = schemas.parse_thread_body(request.get_json(silent=True))
    return jsonify(forum_service.update_thread(g.actor, thread_id, title, body))


@bp.delete("/threads/<thread_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def delete_thread(thread_id: str) -> Any:
    return jsonify(forum_service.delete_thread(g.actor, thread_id))


@bp.post("/threads/<thread_id>/comments")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def create_comment(thread_id: str) -> Any:
    forum_service.authorize_thread_view(g.actor, thread_id)
    body = schemas.parse_comment_body(request.get_json(silent=True))
    return jsonify(forum_service.create_comment(g.actor, thread_id, body)), 201


@bp.get("/threads/<thread_id>/comments")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_comments(thread_id: str) -> Any:
    return jsonify(forum_service.list_comments(g.actor, thread_id))


@bp.patch("/comments/<comment_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def update_comment(comment_id: str) -> Any:
    body = schemas.parse_comment_body(request.get_json(silent=True))
    return jsonify(forum_service.update_comment(g.actor, comment_id, body))


@bp.delete("/comments/<comment_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def delete_comment(comment_id: str) -> Any:
    return jsonify(forum_service.delete_comment(g.actor, comment_id))
