"""Chứng chỉ hoàn thành khoá học và bảng xếp hạng."""

import uuid
from typing import Any

from . import audit, badge_service, lesson_service
from . import store as store_module
from .errors import Conflict, Forbidden, NotFound, ValidationError
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


def set_rule(
    actor: dict[str, Any], course_id: str, min_grade: float | None, require_lessons: bool
) -> dict[str, Any]:
    if min_grade is not None and (
        not isinstance(min_grade, (int, float)) or not 0 <= min_grade <= 10
    ):
        raise ValidationError()
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        updated = store_module.set_course_cert_rule(
            state,
            course_id,
            min_grade=float(min_grade) if min_grade is not None else None,
            require_lessons=bool(require_lessons),
        )
        if updated is None:
            raise NotFound()
        audit.record(
            actor["id"],
            "CERT_RULE_SET",
            f"/courses/{course_id}/certificate-rule",
            "OK",
            courseId=course_id,
            path=state["audit_log_path"],
        )
        return {
            "courseId": course_id,
            "certMinGrade": updated.get("certMinGrade"),
            "certRequireLessons": bool(updated.get("certRequireLessons", True)),
        }


def _eligibility(state: dict[str, Any], course: dict[str, Any], student_id: str) -> bool:
    report = store_module.course_report(state, course["id"])
    if report is None:
        return False
    mine = next((item for item in report["students"] if item["studentId"] == student_id), None)
    if mine is None:
        return False
    if course.get("certRequireLessons", True) and (mine["lessonsDone"] < mine["lessonsTotal"]):
        return False
    min_grade = course.get("certMinGrade")
    return not (
        min_grade is not None and (mine["avgGrade"] is None or mine["avgGrade"] < float(min_grade))
    )


def _new_code() -> str:
    return "CERT-" + uuid.uuid4().hex[:12].upper()


def issue(actor: dict[str, Any], course_id: str, student_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        student = state["users"].get(student_id)
        if student is None or student["role"] != "STUDENT":
            raise ValidationError()
        if (course_id, student_id) not in state["enrollments"]:
            raise ValidationError()
        if store_module.list_certificates(state, course_id=course_id, student_id=student_id):
            raise Conflict()
        certificate = store_module.create_certificate(
            state,
            course_id=course_id,
            student_id=student_id,
            code=_new_code(),
            issued_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "CERT_ISSUE",
            f"/courses/{course_id}/certificates",
            "OK",
            certificateId=certificate["id"],
            path=state["audit_log_path"],
        )
        certificate["courseName"] = course["name"]
        certificate["studentName"] = (
            student.get("name") or student.get("email", "") or student.get("email", "")
        )
        return certificate


def revoke(actor: dict[str, Any], certificate_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        certificate = store_module.get_certificate(state, certificate_id)
        if certificate is None:
            raise NotFound()
        course = _course(state, certificate["courseId"])
        if not _can_manage(actor, course):
            raise Forbidden()
        if not store_module.revoke_certificate(state, certificate_id, state["now"]()):
            raise Conflict()
        return {"id": certificate_id, "revoked": True}


def list_course(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        certificates = store_module.list_certificates(state, course_id=course_id)
        for item in certificates:
            item["studentName"] = (state["users"].get(item["studentId"]) or {}).get("name", "")
            item["courseName"] = course["name"]
        return certificates


def my_certificates(actor: dict[str, Any]) -> list[dict[str, Any]]:
    """Danh sách chứng chỉ của sinh viên; tự cấp khi đủ điều kiện."""
    if _role(actor) != "STUDENT":
        raise Forbidden()
    state = current_store()
    student_id = str(actor.get("id"))
    with state["lock"]:
        badges = badge_service.check_auto(state, student_id)
        del badges
        result = []
        for course_id, sid in list(state["enrollments"]):
            if sid != student_id:
                continue
            course = state["courses"].get(course_id)
            if course is None:
                continue
            certificates = store_module.list_certificates(
                state, course_id=course_id, student_id=student_id
            )
            if not certificates and _eligibility(state, course, student_id):
                certificate = store_module.create_certificate(
                    state,
                    course_id=course_id,
                    student_id=student_id,
                    code=_new_code(),
                    issued_by=None,
                    now=state["now"](),
                )
                certificates = [certificate]
            for item in certificates:
                item["courseName"] = course["name"]
                result.append(item)
        return result


def certificate_data(actor: dict[str, Any], certificate_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        certificate = store_module.get_certificate(state, certificate_id)
        if certificate is None:
            raise NotFound()
        course = _course(state, certificate["courseId"])
        if certificate["studentId"] != actor.get("id") and not _can_manage(actor, course):
            raise Forbidden()
        student = state["users"].get(certificate["studentId"]) or {}
        certificate["courseName"] = course["name"]
        certificate["studentName"] = student.get("name") or student.get("email", "")
        certificate["instructorName"] = (state["users"].get(course["instructorId"]) or {}).get(
            "name", ""
        )
        return certificate


def course_leaderboard(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        lesson_service.authorize_view(actor, course_id)
        report = store_module.course_report(state, course_id)
        if report is None:
            raise NotFound()
        ranking = []
        for item in report["students"]:
            points = (
                item["lessonsDone"] * 5
                + (item["avgGrade"] or 0) * 10
                + (item["avgQuizScore"] or 0) * 10
                + (item["bestQuizScore"] or 0) * 5
            )
            ranking.append(
                {
                    "studentId": item["studentId"],
                    "name": item["name"],
                    "email": item["email"],
                    "points": round(points, 2),
                    "lessonsDone": item["lessonsDone"],
                    "avgGrade": item["avgGrade"],
                    "avgQuizScore": item["avgQuizScore"],
                }
            )
        ranking.sort(key=lambda row: row["points"], reverse=True)
        for index, row in enumerate(ranking, 1):
            row["rank"] = index
        return ranking
