"""Endpoint bài kiểm tra trắc nghiệm và chấm điểm tự động (Blueprint riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import quiz_service, schemas
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("quizzes", __name__)


@bp.post("/courses/<course_id>/quizzes")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def create_quiz(course_id: str) -> Any:
    title, description, duration, max_attempts, questions, allow_answers = schemas.parse_quiz_body(
        request.get_json(silent=True)
    )
    return (
        jsonify(
            quiz_service.create_quiz(
                g.actor,
                course_id=course_id,
                title=title,
                description=description,
                duration_minutes=duration,
                max_attempts=max_attempts,
                questions=questions,
                allow_answers=allow_answers,
            )
        ),
        201,
    )


@bp.get("/courses/<course_id>/quizzes")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_quizzes(course_id: str) -> Any:
    return jsonify(quiz_service.list_quizzes(g.actor, course_id))


@bp.get("/quizzes/<quiz_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def get_quiz(quiz_id: str) -> Any:
    return jsonify(quiz_service.get_quiz(g.actor, quiz_id))


@bp.delete("/quizzes/<quiz_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def delete_quiz(quiz_id: str) -> Any:
    return jsonify(quiz_service.delete_quiz(g.actor, quiz_id))


@bp.post("/quizzes/<quiz_id>/attempts")
@require_role("STUDENT")
@store_scope
def start_attempt(quiz_id: str) -> Any:
    return jsonify(quiz_service.start_attempt(g.actor, quiz_id)), 201


@bp.post("/quizzes/<quiz_id>/attempts/<attempt_id>/submit")
@require_role("STUDENT")
@store_scope
def submit_attempt(quiz_id: str, attempt_id: str) -> Any:
    answers = schemas.parse_quiz_submit_body(request.get_json(silent=True))
    return jsonify(quiz_service.submit_attempt(g.actor, attempt_id, answers))


@bp.patch("/quizzes/<quiz_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def update_quiz(quiz_id: str) -> Any:
    title, description, duration, max_attempts, questions, allow_answers = schemas.parse_quiz_body(
        request.get_json(silent=True)
    )
    return jsonify(
        quiz_service.update_quiz(
            g.actor,
            quiz_id,
            title=title,
            description=description,
            duration_minutes=duration,
            max_attempts=max_attempts,
            questions=questions,
            allow_answers=allow_answers,
        )
    )


@bp.get("/quiz-attempts/<attempt_id>/answers")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def attempt_answers(attempt_id: str) -> Any:
    return jsonify(quiz_service.get_attempt_answers(g.actor, attempt_id))


@bp.get("/quizzes/<quiz_id>/attempts")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_attempts(quiz_id: str) -> Any:
    return jsonify(quiz_service.list_attempts(g.actor, quiz_id))
