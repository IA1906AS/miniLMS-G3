"""Báo cáo tiến độ và điểm số (không import Flask)."""

from typing import Any

from . import store as store_module
from .errors import Forbidden, NotFound
from .runtime import current_store


def _role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def _can_manage(actor: dict[str, Any], course: dict[str, Any]) -> bool:
    return _role(actor) == "ADMIN" or (
        _role(actor) == "INSTRUCTOR" and course["instructorId"] == actor.get("id")
    )


def course_report(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = state["courses"].get(course_id)
        if course is None:
            raise NotFound()
        if not _can_manage(actor, course):
            raise Forbidden()
        report = store_module.course_report(state, course_id)
        if report is None:
            raise NotFound()
        report["courseName"] = course["name"]
        return report


def student_progress(actor: dict[str, Any]) -> list[dict[str, Any]]:
    """Tiến độ của chính sinh viên trong các khoá đã ghi danh."""
    state = current_store()
    result = []
    with state["lock"]:
        course_ids = [
            course_id for (course_id, sid) in state["enrollments"] if sid == actor.get("id")
        ]
        for course_id in course_ids:
            report = store_module.course_report(state, course_id)
            if report is None:
                continue
            mine = next(
                (item for item in report["students"] if item["studentId"] == actor.get("id")),
                None,
            )
            if mine is None:
                continue
            mine = dict(mine)
            mine["courseId"] = course_id
            mine["courseName"] = state["courses"][course_id]["name"]
            total = mine["lessonsTotal"] or 0
            mine["lessonsPercent"] = round(mine["lessonsDone"] * 100 / total, 2) if total else 0.0
            result.append(mine)
    return result


def system_report(actor: dict[str, Any]) -> dict[str, Any]:
    if _role(actor) != "ADMIN":
        raise Forbidden()
    state = current_store()
    with state["lock"]:
        users = list(state["users"].values())
        by_role = {
            role: len([user for user in users if user["role"] == role])
            for role in ("ADMIN", "INSTRUCTOR", "STUDENT")
        }
        return {
            "users": len(users),
            "byRole": by_role,
            "courses": len(state["courses"]),
            "publishedCourses": len(
                [course for course in state["courses"].values() if course.get("published", True)]
            ),
            "enrollments": len(state["enrollments"]),
        }


def csv_rows(report: dict[str, Any]) -> list[list[str]]:
    rows = [
        [
            "email",
            "ho_ten",
            "bai_hoc_hoan_thanh",
            "tong_bai_hoc",
            "bai_tap_da_nop",
            "bai_tap_da_cham",
            "diem_trung_binh",
            "luot_quiz",
            "diem_quiz_tb",
            "ket_qua",
        ]
    ]
    for item in report["students"]:
        rows.append(
            [
                str(item["email"]),
                str(item["name"]),
                str(item["lessonsDone"]),
                str(item["lessonsTotal"]),
                str(item["assignmentsSubmitted"]),
                str(item["assignmentsGraded"]),
                "" if item["avgGrade"] is None else f"{item['avgGrade']:.2f}",
                str(item["quizAttempts"]),
                "" if item["avgQuizScore"] is None else f"{item['avgQuizScore']:.2f}",
                "PASS" if item["passed"] else "FAIL",
            ]
        )
    return rows
