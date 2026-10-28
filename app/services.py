import contextlib
import contextvars
from collections.abc import Iterator
from typing import Any

from . import audit, schemas, store as store_module
from .errors import Forbidden, NotFound


_active_store: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("lms_service_store", default=None)
)


@contextlib.contextmanager
def using_store(store: dict[str, Any]) -> Iterator[None]:
    token = _active_store.set(store)
    try:
        yield
    finally:
        _active_store.reset(token)


def _store() -> dict[str, Any]:
    store = _active_store.get()
    if store is None:
        store = store_module.db
    if store is None:
        raise RuntimeError("The LMS store has not been initialized")
    return store


def _actor_role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def _course(course_id: str) -> dict[str, Any]:
    course = _store()["courses"].get(course_id)
    if course is None:
        raise NotFound()
    return course


def get_grades(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    store = _store()
    with store["lock"]:
        course = _course(course_id)

        role = _actor_role(actor)
        if role == "ADMIN":
            visible = store["enrollments"]
        elif role == "INSTRUCTOR":
            if course["instructorId"] != actor.get("id"):
                raise Forbidden()
            visible = store["enrollments"]
        elif role == "STUDENT":
            visible = [
                (course_student, score)
                for course_student, score in store["enrollments"].items()
                if course_student == (course_id, actor.get("id"))
            ]
            if not visible:
                raise Forbidden()
        else:
            raise Forbidden()

        return [
            {"studentId": course_student[1], "score": score}
            for course_student, score in (
                visible.items() if role in ("ADMIN", "INSTRUCTOR") else visible
            )
            if course_student[0] == course_id
        ]


def authorize_update(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    course = _course(course_id)
    if _actor_role(actor) != "INSTRUCTOR" or course["instructorId"] != actor.get("id"):
        raise Forbidden()
    return course


def ensure_update_access(actor: dict[str, Any], course_id: str) -> None:
    authorize_update(actor, course_id)


def update_grade(
    actor: dict[str, Any],
    course_id: str,
    student_id: str,
    score: int | float,
) -> dict[str, Any]:
    store = _store()
    with store["lock"]:
        authorize_update(actor, course_id)
        score = schemas.validate_score(score)

        enrollment_key = (course_id, student_id)
        if enrollment_key not in store["enrollments"]:
            raise NotFound()

        old_score = store["enrollments"][enrollment_key]
        audit.record(
            actor["id"],
            "UPDATE_GRADE",
            f"/courses/{course_id}/grades/{student_id}",
            "OK",
            oldScore=old_score,
            newScore=score,
            path=store["audit_log_path"],
        )
        store_module.update_grade(store, course_id, student_id, score)
        return {"courseId": course_id, "studentId": student_id, "score": score}
