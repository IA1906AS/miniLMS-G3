"""Bước 3.2 — endpoint khoá học, yêu cầu mở môn và ghi danh (blueprint riêng)."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import course_service, schemas
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("courses", __name__)


@bp.get("/courses")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_courses() -> Any:
    q = request.args.get("q")
    instructor = request.args.get("instructor")
    return jsonify(course_service.list_courses(g.actor, q=q, instructor_id=instructor))


@bp.patch("/courses/<course_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def update_course(course_id: str) -> Any:
    name = schemas.parse_course_update_body(request.get_json(silent=True))
    return jsonify(course_service.update_course(g.actor, course_id, name))


@bp.delete("/courses/<course_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def delete_course(course_id: str) -> Any:
    return jsonify(course_service.delete_course(g.actor, course_id))


@bp.patch("/courses/<course_id>/publish")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def publish_course(course_id: str) -> Any:
    published = schemas.parse_publish_body(request.get_json(silent=True))
    return jsonify(course_service.set_course_published(g.actor, course_id, published))


@bp.get("/courses/<course_id>/members")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_members(course_id: str) -> Any:
    return jsonify(course_service.list_course_members(g.actor, course_id))


@bp.post("/courses")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def create_course() -> Any:
    name, instructor_id = schemas.parse_course_body(request.get_json(silent=True))
    return jsonify(course_service.create_course(g.actor, name, instructor_id)), 201


@bp.get("/courses/<course_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def course_detail(course_id: str) -> Any:
    return jsonify(course_service.get_course(g.actor, course_id))


@bp.post("/course-requests")
@require_role("INSTRUCTOR")
@store_scope
def request_course() -> Any:
    name = schemas.parse_course_request_body(request.get_json(silent=True))
    return jsonify(course_service.request_course(g.actor, name)), 201


@bp.get("/course-requests")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def list_course_requests() -> Any:
    return jsonify(course_service.list_course_requests(g.actor))


@bp.post("/course-requests/<request_id>/approve")
@require_role("ADMIN")
@store_scope
def approve_course_request(request_id: str) -> Any:
    return jsonify(course_service.approve_course_request(g.actor, request_id))


@bp.post("/course-requests/<request_id>/reject")
@require_role("ADMIN")
@store_scope
def reject_course_request(request_id: str) -> Any:
    return jsonify(course_service.reject_course_request(g.actor, request_id))


@bp.post("/courses/<course_id>/enrollments")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def add_enrollment(course_id: str) -> Any:
    course_service.authorize_manage(g.actor, course_id)
    student_id = schemas.parse_enrollment_body(request.get_json(silent=True))
    return jsonify(course_service.enroll_student(g.actor, course_id, student_id)), 201


@bp.delete("/courses/<course_id>/enrollments/<student_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def remove_enrollment(course_id: str, student_id: str) -> Any:
    course_service.authorize_manage(g.actor, course_id)
    return jsonify(course_service.unenroll_student(g.actor, course_id, student_id))


@bp.get("/me/grades")
@require_role("STUDENT")
@store_scope
def own_grades() -> Any:
    return jsonify(course_service.my_grades(g.actor))
