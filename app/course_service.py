"""Bước 3.2 — nghiệp vụ khoá học và ghi danh.

Không import Flask. Mọi kiểm tra quyền được lặp lại ở đây để gọi trực tiếp vẫn an toàn.
"""

import uuid
from typing import Any

from . import audit
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


def _course_view(course: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": course["id"],
        "name": course["name"],
        "instructorId": course["instructorId"],
    }


def list_courses(
    actor: dict[str, Any],
    q: str | None = None,
    instructor_id: str | None = None,
) -> list[dict[str, Any]]:
    state = current_store()
    role = _role(actor)
    with state["lock"]:
        courses = list(state["courses"].values())
        if role == "ADMIN":
            visible = courses
        elif role == "INSTRUCTOR":
            visible = [course for course in courses if course["instructorId"] == actor.get("id")]
        elif role == "STUDENT":
            visible = [
                course
                for course in courses
                if (course["id"], actor.get("id")) in state["enrollments"]
            ]
        else:
            raise Forbidden()
        if q is not None and q.strip():
            visible = [c for c in visible if q.strip().lower() in c["name"].lower()]
        if instructor_id is not None and instructor_id.strip():
            visible = [c for c in visible if c["instructorId"] == instructor_id.strip()]
        return [_course_view(course) for course in visible]


def get_course(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    role = _role(actor)
    with state["lock"]:
        course = _course(state, course_id)
        if role == "ADMIN":
            return _course_view(course)
        if role == "INSTRUCTOR" and course["instructorId"] == actor.get("id"):
            return _course_view(course)
        if role == "STUDENT" and (course_id, actor.get("id")) in state["enrollments"]:
            return _course_view(course)
        raise Forbidden()


def create_course(actor: dict[str, Any], name: str, instructor_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        if _role(actor) != "ADMIN":
            raise Forbidden()
        instructor = state["users"].get(instructor_id)
        if instructor is None:
            raise NotFound()
        if instructor["role"] != "INSTRUCTOR":
            raise ValidationError()

        course = store_module.create_course(state, name=name, instructor_id=instructor_id)
        audit.record(
            actor["id"],
            "COURSE_CREATE",
            "/courses",
            "OK",
            courseId=course["id"],
            path=state["audit_log_path"],
        )
        return _course_view(course)


def update_course(actor: dict[str, Any], course_id: str, name: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        course = store_module.update_course(state, course_id, name)
        if course is None:
            raise NotFound()
        audit.record(
            actor["id"],
            "COURSE_UPDATE",
            f"/courses/{course_id}",
            "OK",
            courseId=course_id,
            path=state["audit_log_path"],
        )
        return _course_view(course)


def delete_course(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        if _role(actor) != "ADMIN":
            raise Forbidden()
        if course_id not in state["courses"]:
            raise NotFound()
        if not store_module.delete_course(state, course_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "COURSE_DELETE",
            f"/courses/{course_id}",
            "OK",
            courseId=course_id,
            path=state["audit_log_path"],
        )
        return {"id": course_id, "deleted": True}


def list_course_members(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    role = _role(actor)
    with state["lock"]:
        course = _course(state, course_id)
        if role == "ADMIN":
            pass
        elif role == "INSTRUCTOR" and course["instructorId"] == actor.get("id"):
            pass
        elif role == "STUDENT" and (course_id, actor.get("id")) in state["enrollments"]:
            pass
        else:
            raise Forbidden()
        return store_module.list_course_members(state, course_id)


def request_course(actor: dict[str, Any], name: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        if _role(actor) != "INSTRUCTOR":
            raise Forbidden()
        request = store_module.create_course_request(
            state,
            name=name,
            instructor_id=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "COURSE_REQUEST",
            "/course-requests",
            "OK",
            requestId=request["id"],
            path=state["audit_log_path"],
        )
        return request


def list_course_requests(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    role = _role(actor)
    with state["lock"]:
        if role == "ADMIN":
            return store_module.list_course_requests(state)
        if role == "INSTRUCTOR":
            return store_module.list_course_requests(state, instructor_id=str(actor.get("id")))
        raise Forbidden()


def approve_course_request(actor: dict[str, Any], request_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        if _role(actor) != "ADMIN":
            raise Forbidden()
        request = store_module.get_course_request(state, request_id)
        if request is None:
            raise NotFound()
        if request["status"] != "PENDING":
            raise Conflict()

        course = {
            "id": "c_" + uuid.uuid4().hex,
            "name": request["name"],
            "instructorId": request["instructorId"],
        }
        approved = store_module.approve_course_request(
            state,
            request_id=request_id,
            course=course,
            decided_by=str(actor.get("id")),
            now=state["now"](),
        )
        if not approved:
            raise Conflict()
        audit.record(
            actor["id"],
            "COURSE_APPROVE",
            f"/course-requests/{request_id}/approve",
            "OK",
            courseId=course["id"],
            path=state["audit_log_path"],
        )
        return _course_view(course)


def reject_course_request(actor: dict[str, Any], request_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        if _role(actor) != "ADMIN":
            raise Forbidden()
        request = store_module.get_course_request(state, request_id)
        if request is None:
            raise NotFound()
        if not store_module.reject_course_request(
            state,
            request_id=request_id,
            decided_by=str(actor.get("id")),
            now=state["now"](),
        ):
            raise Conflict()
        audit.record(
            actor["id"],
            "COURSE_REJECT",
            f"/course-requests/{request_id}/reject",
            "OK",
            path=state["audit_log_path"],
        )
        return {"id": request_id, "status": "REJECTED"}


def authorize_manage(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """404 nếu môn không tồn tại, 403 nếu không phải ADMIN/GV dạy môn."""
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if _role(actor) == "ADMIN":
            return course
        if _role(actor) == "INSTRUCTOR" and course["instructorId"] == actor.get("id"):
            return course
        raise Forbidden()


def enroll_student(actor: dict[str, Any], course_id: str, student_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        student = state["users"].get(student_id)
        if student is None:
            raise NotFound()
        if student["role"] != "STUDENT":
            raise ValidationError()
        try:
            store_module.add_enrollment(state, course_id, student_id)
        except ValueError as error:
            raise Conflict() from error

        audit.record(
            actor["id"],
            "ENROLL_STUDENT",
            f"/courses/{course_id}/enrollments",
            "OK",
            studentId=student_id,
            path=state["audit_log_path"],
        )
        return {"courseId": course_id, "studentId": student_id}


def unenroll_student(actor: dict[str, Any], course_id: str, student_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        if not store_module.remove_enrollment(state, course_id, student_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "UNENROLL_STUDENT",
            f"/courses/{course_id}/enrollments/{student_id}",
            "OK",
            studentId=student_id,
            path=state["audit_log_path"],
        )
        return {"courseId": course_id, "studentId": student_id, "removed": True}


def my_grades(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    if _role(actor) != "STUDENT":
        raise Forbidden()
    student_id = actor.get("id")
    with state["lock"]:
        return [
            {
                "courseId": course_id,
                "courseName": state["courses"][course_id]["name"],
                "score": score,
            }
            for (course_id, enrolled_id), score in state["enrollments"].items()
            if enrolled_id == student_id and course_id in state["courses"]
        ]
