from typing import Any

from . import audit, emailer, schemas
from . import store as store_module
from .errors import Conflict, Forbidden, NotFound
from .runtime import current_store as _store
from .runtime import using_store  # re-export: tương thích với code/test cũ

__all__ = [
    "authorize_update",
    "enroll_in_course",
    "get_grades",
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


def enroll_in_course(actor: dict[str, Any], course_id: str, config: Any) -> dict[str, Any]:
    """Đăng ký học phần rồi gửi email xác nhận ngay trong request (bản Before, chưa có outbox).

    Hai lần ghi (PostgreSQL rồi SMTP) không nằm trong cùng một transaction: nếu SMTP lỗi thì
    đăng ký đã commit nhưng email bị mất và không có cơ chế gửi lại.
    """
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
        try:
            store_module.add_enrollment(store, course_id, student_id)
        except ValueError as error:
            raise Conflict() from error

        student_name = str(user.get("name") or "").strip()
        greeting = f"Chào {student_name}," if student_name else "Chào bạn,"
        body = (
            f"{greeting}\n\n"
            f'Bạn đã đăng ký thành công khóa học "{course["name"]}" '
            f"(mã khóa học: {course_id}).\n"
            "Điểm của bạn hiện là 0.0 và sẽ được giảng viên cập nhật trong khóa học.\n\n"
            "Nếu bạn không thực hiện đăng ký này, hãy liên hệ quản trị viên.\n"
        )
        emailer.send_email(
            config,
            str(student_email),
            f"Xác nhận đăng ký khóa học {course['name']}",
            body,
        )

        audit.record(
            student_id,
            "ENROLL_COURSE",
            f"/courses/{course_id}/enrollments",
            "OK",
            path=store["audit_log_path"],
        )
        return {"courseId": course_id, "studentId": student_id, "score": 0.0}
