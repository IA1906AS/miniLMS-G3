"""Nghiệp vụ bài học (lessons) và tiến độ học.

Bài học thuộc một khoá học; giảng viên phụ trách/ADMIN quản lý, sinh viên đã ghi danh
xem và đánh dấu hoàn thành. Không import Flask.
"""

import datetime
from typing import Any

from . import audit, badge_service
from . import store as store_module
from .errors import Forbidden, NotFound, ValidationError
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


def authorize_manage(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        return course


def authorize_view(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if _can_manage(actor, course):
            return course
        if _role(actor) == "STUDENT" and (course_id, actor.get("id")) in state["enrollments"]:
            return course
        raise Forbidden()


def _validate(title: str, body: str, video_url: str) -> None:
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValidationError()
    if not isinstance(body, str) or len(body) > 20000:
        raise ValidationError()
    if not isinstance(video_url, str) or len(video_url) > 500:
        raise ValidationError()


def create_lesson(
    actor: dict[str, Any],
    course_id: str,
    title: str,
    body: str = "",
    video_url: str = "",
    is_preview: bool = False,
) -> dict[str, Any]:
    _validate(title, body, video_url)
    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        lesson = store_module.create_lesson(
            state,
            course_id=course_id,
            title=title.strip(),
            body=body,
            video_url=video_url,
            is_preview=bool(is_preview),
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "LESSON_CREATE",
            f"/courses/{course_id}/lessons",
            "OK",
            lessonId=lesson["id"],
            path=state["audit_log_path"],
        )
        return lesson


def update_lesson(
    actor: dict[str, Any],
    lesson_id: str,
    title: str,
    body: str,
    video_url: str,
    is_preview: bool,
) -> dict[str, Any]:
    _validate(title, body, video_url)
    state = current_store()
    with state["lock"]:
        lesson = store_module.get_lesson(state, lesson_id)
        if lesson is None:
            raise NotFound()
        authorize_manage(actor, lesson["courseId"])
        if not store_module.update_lesson(
            state,
            lesson_id,
            title=title.strip(),
            body=body,
            video_url=video_url,
            is_preview=bool(is_preview),
        ):
            raise NotFound()
        audit.record(
            actor["id"],
            "LESSON_UPDATE",
            f"/lessons/{lesson_id}",
            "OK",
            lessonId=lesson_id,
            path=state["audit_log_path"],
        )
        return store_module.get_lesson(state, lesson_id) or {}


def delete_lesson(actor: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        lesson = store_module.get_lesson(state, lesson_id)
        if lesson is None:
            raise NotFound()
        authorize_manage(actor, lesson["courseId"])
        if not store_module.delete_lesson(state, lesson_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "LESSON_DELETE",
            f"/lessons/{lesson_id}",
            "OK",
            lessonId=lesson_id,
            path=state["audit_log_path"],
        )
        return {"id": lesson_id, "deleted": True}


def list_lessons(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        return store_module.list_lessons(state, course_id)


def get_lesson(actor: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        lesson = store_module.get_lesson(state, lesson_id)
        if lesson is None:
            raise NotFound()
        authorize_view(actor, lesson["courseId"])
        return lesson


def complete_lesson(actor: dict[str, Any], lesson_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        lesson = store_module.get_lesson(state, lesson_id)
        if lesson is None:
            raise NotFound()
        if _role(actor) != "STUDENT":
            raise Forbidden()
        if (lesson["courseId"], actor.get("id")) not in state["enrollments"]:
            raise Forbidden()
        store_module.mark_lesson_complete(
            state, user_id=str(actor.get("id")), lesson_id=lesson_id, now=state["now"]()
        )
        store_module.record_activity(state, str(actor.get("id")), datetime.date.today().isoformat())
        badge_service.check_auto(state, str(actor.get("id")))
        audit.record(
            actor["id"],
            "LESSON_COMPLETE",
            f"/lessons/{lesson_id}/complete",
            "OK",
            lessonId=lesson_id,
            path=state["audit_log_path"],
        )
        return {"lessonId": lesson_id, "completed": True}


def course_progress(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """Tiến độ của chính actor trong khoá học: số bài đã hoàn thành / tổng số bài."""
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        lessons = store_module.list_lessons(state, course_id)
        completed = store_module.completed_lesson_ids(state, str(actor.get("id")), course_id)
    total = len(lessons)
    done = len([lesson for lesson in lessons if lesson["id"] in completed])
    return {
        "courseId": course_id,
        "totalLessons": total,
        "completedLessons": done,
        "percent": round(done * 100 / total, 2) if total else 0.0,
        "lessonIds": [lesson["id"] for lesson in lessons],
        "completedIds": sorted(completed),
    }
