"""Cộng đồng: tin nhắn, live session và bình luận bài học."""

from typing import Any

from . import audit, lesson_service
from . import store as store_module
from .errors import Forbidden, NotFound, ValidationError
from .runtime import current_store


def _role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def _user(state: dict[str, Any], user_id: str) -> dict[str, Any]:
    user = state["users"].get(user_id)
    if user is None:
        raise NotFound()
    return user


def _shares_course(state: dict[str, Any], first: str, second: str) -> bool:
    first_courses = {course_id for (course_id, sid) in state["enrollments"] if sid == first}
    second_courses = {course_id for (course_id, sid) in state["enrollments"] if sid == second}
    if first_courses & second_courses:
        return True
    # giảng viên phụ trách khoá mà người kia đang học
    for course_id, sid in state["enrollments"]:
        if sid != second:
            continue
        course = state["courses"].get(course_id)
        if course is not None and course["instructorId"] == first:
            return True
    for course_id, sid in state["enrollments"]:
        if sid != first:
            continue
        course = state["courses"].get(course_id)
        if course is not None and course["instructorId"] == second:
            return True
    return False


def send_message(actor: dict[str, Any], recipient_id: str, body: str) -> dict[str, Any]:
    if not isinstance(body, str) or not body.strip() or len(body) > 2000:
        raise ValidationError()
    state = current_store()
    with state["lock"]:
        _user(state, recipient_id)
        if recipient_id == actor.get("id"):
            raise ValidationError()
        if _role(actor) != "ADMIN" and not _shares_course(
            state, str(actor.get("id")), recipient_id
        ):
            raise Forbidden()
        message = store_module.create_message(
            state,
            sender_id=str(actor.get("id")),
            recipient_id=recipient_id,
            body=body.strip(),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "MESSAGE_SEND",
            f"/messages/{recipient_id}",
            "OK",
            path=state["audit_log_path"],
        )
        return message


def conversations(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        items = store_module.list_conversations(state, str(actor.get("id")))
        for item in items:
            partner = state["users"].get(item["userId"]) or {}
            item["name"] = partner.get("name", "")
            item["email"] = partner.get("email", "")
        return items


def thread(actor: dict[str, Any], other_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        _user(state, other_id)
        if _role(actor) != "ADMIN" and not _shares_course(state, str(actor.get("id")), other_id):
            raise Forbidden()
        store_module.mark_messages_read(state, str(actor.get("id")), other_id, state["now"]())
        messages = store_module.list_messages(state, str(actor.get("id")), other_id)
        for message in messages:
            message["senderName"] = (state["users"].get(message["senderId"]) or {}).get("name", "")
        return messages


def create_live_session(
    actor: dict[str, Any], course_id: str, title: str, url: str, starts_at: float
) -> dict[str, Any]:
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValidationError()
    if not isinstance(url, str) or not url.startswith(("http://", "https://")) or len(url) > 500:
        raise ValidationError()
    state = current_store()
    with state["lock"]:
        lesson_service.authorize_manage(actor, course_id)
        session = store_module.create_live_session(
            state,
            course_id=course_id,
            title=title.strip(),
            url=url,
            starts_at=float(starts_at),
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "LIVE_CREATE",
            f"/courses/{course_id}/live",
            "OK",
            sessionId=session["id"],
            path=state["audit_log_path"],
        )
        return session


def list_live_sessions(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        lesson_service.authorize_view(actor, course_id)
        return store_module.list_live_sessions(state, course_id)


def delete_live_session(actor: dict[str, Any], session_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        session = store_module.get_live_session(state, session_id)
        if session is None:
            raise NotFound()
        lesson_service.authorize_manage(actor, session["courseId"])
        store_module.delete_live_session(state, session_id)
        return {"id": session_id, "deleted": True}


def add_lesson_comment(actor: dict[str, Any], lesson_id: str, body: str) -> dict[str, Any]:
    if not isinstance(body, str) or not body.strip() or len(body) > 2000:
        raise ValidationError()
    state = current_store()
    with state["lock"]:
        lesson = store_module.get_lesson(state, lesson_id)
        if lesson is None:
            raise NotFound()
        lesson_service.authorize_view(actor, lesson["courseId"])
        return store_module.create_lesson_comment(
            state,
            lesson_id=lesson_id,
            user_id=str(actor.get("id")),
            body=body.strip(),
            now=state["now"](),
        )


def list_lesson_comments(actor: dict[str, Any], lesson_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        lesson = store_module.get_lesson(state, lesson_id)
        if lesson is None:
            raise NotFound()
        lesson_service.authorize_view(actor, lesson["courseId"])
        return store_module.list_lesson_comments(state, lesson_id)


def delete_lesson_comment(actor: dict[str, Any], comment_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        comment = store_module.get_lesson_comment(state, comment_id)
        if comment is None:
            raise NotFound()
        lesson = store_module.get_lesson(state, comment["lessonId"])
        if lesson is None:
            raise NotFound()
        is_owner = comment["userId"] == actor.get("id")
        if not is_owner:
            lesson_service.authorize_manage(actor, lesson["courseId"])
        store_module.delete_lesson_comment(state, comment_id)
        return {"id": comment_id, "deleted": True}
