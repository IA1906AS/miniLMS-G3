"""Bước 3.4 — bài tập và nộp bài.

Không import Flask. Hạn nộp kiểm tra bằng `state["now"]` để test bơm đồng hồ được.
"""

from typing import Any

from . import audit
from . import store as store_module
from .errors import Conflict, Forbidden, NotFound
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


def _assignment(state: dict[str, Any], assignment_id: str) -> dict[str, Any]:
    assignment = store_module.get_assignment(state, assignment_id)
    if assignment is None:
        raise NotFound()
    return assignment


def authorize_manage(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    """404 nếu môn không tồn tại, 403 nếu không phải ADMIN/GV dạy môn."""
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        return course


def create_assignment(
    actor: dict[str, Any],
    course_id: str,
    title: str,
    description: str,
    due_at: float,
) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        assignment = store_module.create_assignment(
            state,
            course_id=course_id,
            title=title,
            description=description,
            due_at=due_at,
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "ASSIGNMENT_CREATE",
            f"/courses/{course_id}/assignments",
            "OK",
            assignmentId=assignment["id"],
            path=state["audit_log_path"],
        )
        return assignment


def list_assignments(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        role = _role(actor)
        if role == "ADMIN" or _can_manage(actor, course):
            pass
        elif role == "STUDENT":
            if (course_id, actor.get("id")) not in state["enrollments"]:
                raise Forbidden()
        else:
            raise Forbidden()
        return store_module.list_assignments(state, course_id)


def authorize_submit(actor: dict[str, Any], assignment_id: str) -> dict[str, Any]:
    """404 nếu bài tập không có, 403 nếu không phải SV của môn hoặc đã quá hạn."""
    state = current_store()
    with state["lock"]:
        assignment = _assignment(state, assignment_id)
        if _role(actor) != "STUDENT":
            raise Forbidden()
        if (assignment["courseId"], actor.get("id")) not in state["enrollments"]:
            raise Forbidden()
        if state["now"]() > assignment["dueAt"]:
            raise Forbidden()
        return assignment


def submit(
    actor: dict[str, Any],
    assignment_id: str,
    content: str,
    file_name: str = "",
    file_path: str = "",
) -> tuple[dict[str, Any], bool]:
    """Trả (submission, created). Gửi lại cùng nội dung -> (bài cũ, False)."""
    state = current_store()
    with state["lock"]:
        assignment = authorize_submit(actor, assignment_id)
        outcome, submission = store_module.create_submission(
            state,
            assignment_id=assignment["id"],
            student_id=str(actor.get("id")),
            content=content,
            now=state["now"](),
            file_name=file_name,
            file_path=file_path,
        )
        if outcome == "conflict":
            raise Conflict()
        if outcome == "created":
            audit.record(
                actor["id"],
                "SUBMISSION_CREATE",
                f"/assignments/{assignment_id}/submissions",
                "OK",
                submissionId=submission["id"] if submission else None,
                path=state["audit_log_path"],
            )
        return submission or {}, outcome == "created"


def grade_submission(
    actor: dict[str, Any],
    submission_id: str,
    grade: float,
    feedback: str,
) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        submission = store_module.get_submission_by_id(state, submission_id)
        if submission is None:
            raise NotFound()
        assignment = _assignment(state, submission["assignmentId"])
        course = _course(state, assignment["courseId"])
        if not _can_manage(actor, course):
            raise Forbidden()

        graded = store_module.grade_submission(
            state,
            submission_id=submission_id,
            grade=grade,
            feedback=feedback,
            graded_by=str(actor.get("id")),
            now=state["now"](),
        )
        if graded is None:
            raise NotFound()
        audit.record(
            actor["id"],
            "SUBMISSION_GRADE",
            f"/submissions/{submission_id}/grade",
            "OK",
            submissionId=submission_id,
            grade=grade,
            path=state["audit_log_path"],
        )
        return graded


def get_submission_file(
    actor: dict[str, Any],
    submission_id: str,
    upload_dir: str,
) -> tuple[str, str]:
    from . import storage

    state = current_store()
    with state["lock"]:
        submission = store_module.get_submission_by_id(state, submission_id)
        if submission is None:
            raise NotFound()
        assignment = _assignment(state, submission["assignmentId"])
        course = _course(state, assignment["courseId"])

        role = _role(actor)
        if role == "ADMIN" or (
            role == "INSTRUCTOR" and course["instructorId"] == actor.get("id")
        ):
            pass
        elif role == "STUDENT" and submission["studentId"] == actor.get("id"):
            pass
        else:
            raise Forbidden()

        file_path_name = submission.get("filePath")
        if not file_path_name:
            raise NotFound()
        resolved = storage.resolve_file_path(upload_dir, file_path_name)
        if not resolved:
            raise NotFound()
        return resolved, submission.get("fileName", "submission.bin")


def list_submissions(actor: dict[str, Any], assignment_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        assignment = _assignment(state, assignment_id)
        role = _role(actor)
        if role == "ADMIN":
            return store_module.list_submissions(state, assignment_id)
        if role == "INSTRUCTOR":
            course = _course(state, assignment["courseId"])
            if course["instructorId"] != actor.get("id"):
                raise Forbidden()
            return store_module.list_submissions(state, assignment_id)
        if role == "STUDENT":
            if (assignment["courseId"], actor.get("id")) not in state["enrollments"]:
                raise Forbidden()
            own = store_module.get_submission(state, assignment_id, str(actor.get("id")))
            return [own] if own is not None else []
        raise Forbidden()


def my_submissions(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    if _role(actor) != "STUDENT":
        raise Forbidden()
    return store_module.list_student_submissions(state, str(actor.get("id")))
