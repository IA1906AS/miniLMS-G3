import time
from typing import Any

from . import audit, auth, outbox, schemas
from . import store as store_module
from .errors import Conflict, Forbidden, NotFound, ValidationError
from .runtime import current_store as _store
from .runtime import using_store  # re-export: tương thích với code/test cũ

__all__ = [
    "authorize_update",
    "change_role",
    "enroll_in_course",
    "enroll_student",
    "get_course",
    "get_grades",
    "list_courses",
    "list_users",
    "my_grades",
    "unenroll_student",
    "update_grade",
    "using_store",
]


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


def enroll_in_course(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """Enroll the acting student and queue the confirmation email atomically."""
    store = _store()
    with store["lock"]:
        course = _course(course_id)
        if _actor_role(actor) != "STUDENT":
            raise Forbidden()

        student_id = str(actor.get("id"))
        if (course_id, student_id) in store["enrollments"]:
            raise Conflict()

        user = store["users"].get(student_id) or {}
        student_email = actor.get("email") or user.get("email") or ""
        event = outbox.new_event(
            outbox.EVENT_ENROLLMENT_CONFIRMED,
            outbox.enrollment_confirmation_payload(
                student_id=student_id,
                student_email=str(student_email),
                student_name=str(user.get("name", "")),
                course_id=course_id,
                course_name=str(course["name"]),
            ),
        )
        try:
            store_module.create_enrollment(
                store,
                course_id=course_id,
                student_id=student_id,
                event=event,
                now=time.time(),
            )
        except ValueError as error:
            raise Conflict() from error

        audit.record(
            student_id,
            "ENROLL_COURSE",
            f"/courses/{course_id}/enrollments",
            "OK",
            eventId=event["eventId"],
            path=store["audit_log_path"],
        )
        return {
            "courseId": course_id,
            "studentId": student_id,
            "score": 0.0,
            "outboxEventId": event["eventId"],
        }


# --- Giai đoạn 3: phân quyền mở rộng -------------------------------------


def _course_view(course: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": course["id"],
        "name": course["name"],
        "instructorId": course["instructorId"],
    }


def list_courses(actor: dict[str, Any]) -> list[dict[str, Any]]:
    store = _store()
    role = _actor_role(actor)
    with store["lock"]:
        courses = list(store["courses"].values())
        if role == "ADMIN":
            visible = courses
        elif role == "INSTRUCTOR":
            visible = [c for c in courses if c["instructorId"] == actor.get("id")]
        elif role == "STUDENT":
            visible = [c for c in courses if (c["id"], actor.get("id")) in store["enrollments"]]
        else:
            raise Forbidden()
        return [_course_view(course) for course in visible]


def get_course(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    store = _store()
    role = _actor_role(actor)
    with store["lock"]:
        course = _course(course_id)
        if role == "ADMIN":
            return _course_view(course)
        if role == "INSTRUCTOR" and course["instructorId"] == actor.get("id"):
            return _course_view(course)
        if role == "STUDENT" and (course_id, actor.get("id")) in store["enrollments"]:
            return _course_view(course)
        raise Forbidden()


def authorize_manage(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """Kiểm tra môn tồn tại (404) rồi quyền quản lý môn (403)."""
    store = _store()
    with store["lock"]:
        course = _course(course_id)
        if _actor_role(actor) == "ADMIN":
            return course
        if _actor_role(actor) == "INSTRUCTOR" and course["instructorId"] == actor.get("id"):
            return course
        raise Forbidden()


def enroll_student(actor: dict[str, Any], course_id: str, student_id: str) -> dict[str, Any]:
    store = _store()
    with store["lock"]:
        authorize_manage(actor, course_id)
        if student_id not in store["users"]:
            raise NotFound()
        try:
            store_module.add_enrollment(store, course_id, student_id)
        except ValueError as error:
            raise Conflict() from error
        audit.record(
            actor["id"],
            "ENROLL_STUDENT",
            f"/courses/{course_id}/enrollments",
            "OK",
            studentId=student_id,
            path=store["audit_log_path"],
        )
        return {"courseId": course_id, "studentId": student_id}


def unenroll_student(actor: dict[str, Any], course_id: str, student_id: str) -> dict[str, Any]:
    store = _store()
    with store["lock"]:
        authorize_manage(actor, course_id)
        if not store_module.remove_enrollment(store, course_id, student_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "UNENROLL_STUDENT",
            f"/courses/{course_id}/enrollments/{student_id}",
            "OK",
            studentId=student_id,
            path=store["audit_log_path"],
        )
        return {"courseId": course_id, "studentId": student_id, "removed": True}


def my_grades(actor: dict[str, Any]) -> list[dict[str, Any]]:
    store = _store()
    if _actor_role(actor) != "STUDENT":
        raise Forbidden()
    student_id = actor.get("id")
    with store["lock"]:
        return [
            {
                "courseId": course_id,
                "courseName": store["courses"][course_id]["name"],
                "score": score,
            }
            for (course_id, enrolled_id), score in store["enrollments"].items()
            if enrolled_id == student_id and course_id in store["courses"]
        ]


def list_users(actor: dict[str, Any]) -> list[dict[str, Any]]:
    store = _store()
    if _actor_role(actor) != "ADMIN":
        raise Forbidden()
    with store["lock"]:
        return [
            {
                "id": user["id"],
                "email": user["email"],
                "name": user.get("name", ""),
                "role": user["role"],
            }
            for user in store["users"].values()
        ]


def change_role(actor: dict[str, Any], user_id: str, role: str) -> dict[str, Any]:
    store = _store()
    with store["lock"]:
        if _actor_role(actor) != "ADMIN":
            raise Forbidden()
        target = store["users"].get(user_id)
        if target is None:
            raise NotFound()
        if (
            target["role"] == "ADMIN"
            and role != "ADMIN"
            and store_module.count_users_with_role(store, "ADMIN") <= 1
        ):
            raise ValidationError()
        if user_id == actor.get("id") and role != "ADMIN":
            raise ValidationError()

        old_role = target["role"]
        store_module.set_user_role(store, user_id, role)
        auth.invalidate_tokens(store, user_id)
        audit.record(
            actor["id"],
            "ROLE_CHANGE",
            f"/admin/users/{user_id}/role",
            "OK",
            oldRole=old_role,
            newRole=role,
            path=store["audit_log_path"],
        )
        return {
            "id": target["id"],
            "email": target["email"],
            "name": target.get("name", ""),
            "role": role,
        }
