"""Bước 3.5 — thông báo, chủ đề thảo luận và bình luận.

Nội dung là văn bản thuần: không render HTML ở server, trả nguyên văn trong JSON.
Không import Flask.
"""

from typing import Any

from . import audit
from . import store as store_module
from .errors import Forbidden, NotFound
from .runtime import current_store


def _role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def _course(state: dict[str, Any], course_id: str) -> dict[str, Any]:
    course = state["courses"].get(course_id)
    if course is None:
        raise NotFound()
    return course


def _can_manage(actor: dict[str, Any], course: dict[str, Any]) -> bool:
    return _role(actor) == "ADMIN" or (
        _role(actor) == "INSTRUCTOR" and course["instructorId"] == actor.get("id")
    )


def authorize_view(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """ADMIN, giảng viên của môn, hoặc sinh viên đã ghi danh."""
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if _can_manage(actor, course):
            return course
        if _role(actor) == "STUDENT" and (course_id, actor.get("id")) in state["enrollments"]:
            return course
        raise Forbidden()


def authorize_manage(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        return course


def authorize_modify(
    actor: dict[str, Any], course_id: str, created_by: str | None
) -> dict[str, Any]:
    """ADMIN, giảng viên phụ trách hoặc chính chủ sở hữu nội dung."""
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if _can_manage(actor, course) or (created_by is not None and created_by == actor.get("id")):
            return course
        raise Forbidden()


# --- Announcement ---------------------------------------------------------


def create_announcement(
    actor: dict[str, Any], course_id: str, title: str, body: str
) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        announcement = store_module.create_announcement(
            state,
            course_id=course_id,
            title=title,
            body=body,
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "ANNOUNCEMENT_CREATE",
            f"/courses/{course_id}/announcements",
            "OK",
            announcementId=announcement["id"],
            path=state["audit_log_path"],
        )
        return announcement


def list_announcements(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        return store_module.list_announcements(state, course_id)


def delete_announcement(actor: dict[str, Any], announcement_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        announcement = store_module.get_announcement(state, announcement_id)
        if announcement is None:
            raise NotFound()
        authorize_manage(actor, announcement["courseId"])
        if not store_module.delete_announcement(state, announcement_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "ANNOUNCEMENT_DELETE",
            f"/announcements/{announcement_id}",
            "OK",
            path=state["audit_log_path"],
        )
        return {"id": announcement_id, "deleted": True}


# --- Thread ---------------------------------------------------------------


def create_thread(actor: dict[str, Any], course_id: str, title: str, body: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        thread = store_module.create_thread(
            state,
            course_id=course_id,
            title=title,
            body=body,
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "THREAD_CREATE",
            f"/courses/{course_id}/threads",
            "OK",
            threadId=thread["id"],
            path=state["audit_log_path"],
        )
        return thread


def list_threads(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        return store_module.list_threads(state, course_id)


def delete_thread(actor: dict[str, Any], thread_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        thread = store_module.get_thread(state, thread_id)
        if thread is None:
            raise NotFound()
        authorize_modify(actor, thread["courseId"], thread.get("createdBy"))
        if not store_module.delete_thread(state, thread_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "THREAD_DELETE",
            f"/threads/{thread_id}",
            "OK",
            path=state["audit_log_path"],
        )
        return {"id": thread_id, "deleted": True}


# --- Comment --------------------------------------------------------------


def authorize_thread_view(actor: dict[str, Any], thread_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        thread = store_module.get_thread(state, thread_id)
        if thread is None:
            raise NotFound()
        authorize_view(actor, thread["courseId"])
        return thread


def create_comment(actor: dict[str, Any], thread_id: str, body: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        thread = store_module.get_thread(state, thread_id)
        if thread is None:
            raise NotFound()
        authorize_view(actor, thread["courseId"])
        comment = store_module.create_comment(
            state,
            thread_id=thread_id,
            body=body,
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "COMMENT_CREATE",
            f"/threads/{thread_id}/comments",
            "OK",
            commentId=comment["id"],
            path=state["audit_log_path"],
        )
        return comment


def list_comments(actor: dict[str, Any], thread_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        thread = store_module.get_thread(state, thread_id)
        if thread is None:
            raise NotFound()
        authorize_view(actor, thread["courseId"])
        return store_module.list_comments(state, thread_id)


def delete_comment(actor: dict[str, Any], comment_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        comment = store_module.get_comment(state, comment_id)
        if comment is None:
            raise NotFound()
        thread = store_module.get_thread(state, comment["threadId"])
        if thread is None:
            raise NotFound()
        authorize_modify(actor, thread["courseId"], comment.get("createdBy"))
        if not store_module.delete_comment(state, comment_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "COMMENT_DELETE",
            f"/comments/{comment_id}",
            "OK",
            path=state["audit_log_path"],
        )
        return {"id": comment_id, "deleted": True}


def update_thread(actor: dict[str, Any], thread_id: str, title: str, body: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        thread = store_module.get_thread(state, thread_id)
        if thread is None:
            raise NotFound()
        authorize_modify(actor, thread["courseId"], thread.get("createdBy"))
        if not store_module.update_thread(state, thread_id, title=title, body=body):
            raise NotFound()
        audit.record(
            actor["id"],
            "THREAD_UPDATE",
            f"/threads/{thread_id}",
            "OK",
            path=state["audit_log_path"],
        )
        return store_module.get_thread(state, thread_id) or {}


def update_comment(actor: dict[str, Any], comment_id: str, body: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        comment = store_module.get_comment(state, comment_id)
        if comment is None:
            raise NotFound()
        thread = store_module.get_thread(state, comment["threadId"])
        if thread is None:
            raise NotFound()
        authorize_modify(actor, thread["courseId"], comment.get("createdBy"))
        if not store_module.update_comment(state, comment_id, body=body):
            raise NotFound()
        audit.record(
            actor["id"],
            "COMMENT_UPDATE",
            f"/comments/{comment_id}",
            "OK",
            path=state["audit_log_path"],
        )
        return store_module.get_comment(state, comment_id) or {}
