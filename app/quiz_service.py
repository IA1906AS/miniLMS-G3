"""Nghiệp vụ bài kiểm tra trắc nghiệm và chấm điểm tự động.

Toàn bộ việc đối chiếu đáp án và tính điểm được thực hiện hoàn toàn ở phía máy chủ.
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


def create_quiz(
    actor: dict[str, Any],
    course_id: str,
    *,
    title: str,
    description: str,
    duration_minutes: int,
    max_attempts: int,
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        quiz = store_module.create_quiz(
            state,
            course_id=course_id,
            title=title,
            description=description,
            duration_minutes=duration_minutes,
            max_attempts=max_attempts,
            questions=questions,
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "QUIZ_CREATE",
            f"/courses/{course_id}/quizzes",
            "OK",
            quizId=quiz["id"],
            path=state["audit_log_path"],
        )
        return quiz


def list_quizzes(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        return store_module.list_quizzes(state, course_id)


def get_quiz(actor: dict[str, Any], quiz_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        raw_quiz = store_module.get_quiz(state, quiz_id, include_answers=True)
        if raw_quiz is None:
            raise NotFound()
        course = _course(state, raw_quiz["courseId"])
        can_manage = _can_manage(actor, course)
        if not can_manage:
            if (
                _role(actor) != "STUDENT"
                or (raw_quiz["courseId"], actor.get("id")) not in state["enrollments"]
            ):
                raise Forbidden()
            return store_module.get_quiz(state, quiz_id, include_answers=False) or {}
        return raw_quiz


def delete_quiz(actor: dict[str, Any], quiz_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        quiz = store_module.get_quiz(state, quiz_id)
        if quiz is None:
            raise NotFound()
        authorize_manage(actor, quiz["courseId"])
        if not store_module.delete_quiz(state, quiz_id):
            raise NotFound()
        audit.record(
            actor["id"],
            "QUIZ_DELETE",
            f"/quizzes/{quiz_id}",
            "OK",
            quizId=quiz_id,
            path=state["audit_log_path"],
        )
        return {"id": quiz_id, "deleted": True}


def start_attempt(actor: dict[str, Any], quiz_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        quiz = store_module.get_quiz(state, quiz_id, include_answers=False)
        if quiz is None:
            raise NotFound()
        if _role(actor) != "STUDENT":
            raise Forbidden()
        if (quiz["courseId"], actor.get("id")) not in state["enrollments"]:
            raise Forbidden()

        try:
            attempt = store_module.create_quiz_attempt(
                state,
                quiz_id=quiz_id,
                student_id=str(actor.get("id")),
                now=state["now"](),
            )
        except ValueError as error:
            raise Conflict() from error

        attempt["questions"] = quiz.get("questions", [])
        audit.record(
            actor["id"],
            "QUIZ_ATTEMPT_START",
            f"/quizzes/{quiz_id}/attempts",
            "OK",
            attemptId=attempt["id"],
            path=state["audit_log_path"],
        )
        return attempt


def submit_attempt(
    actor: dict[str, Any], attempt_id: str, answers: dict[str, int]
) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        attempt = store_module.get_quiz_attempt(state, attempt_id)
        if attempt is None:
            raise NotFound()
        if attempt["studentId"] != actor.get("id"):
            raise Forbidden()
        if attempt.get("submittedAt") is not None:
            raise Conflict()

        result = store_module.submit_quiz_attempt(
            state,
            attempt_id=attempt_id,
            answers=answers,
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "QUIZ_ATTEMPT_SUBMIT",
            f"/quiz-attempts/{attempt_id}/submit",
            "OK",
            attemptId=attempt_id,
            score=result["score"],
            path=state["audit_log_path"],
        )
        return result


def list_attempts(actor: dict[str, Any], quiz_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        quiz = store_module.get_quiz(state, quiz_id)
        if quiz is None:
            raise NotFound()
        course = _course(state, quiz["courseId"])
        role = _role(actor)
        if _can_manage(actor, course):
            return store_module.list_quiz_attempts(state, quiz_id)
        if role == "STUDENT" and (quiz["courseId"], actor.get("id")) in state["enrollments"]:
            return store_module.list_quiz_attempts(state, quiz_id, student_id=str(actor.get("id")))
        raise Forbidden()
