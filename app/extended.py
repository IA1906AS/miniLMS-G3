"""Giai đoạn 3 — phân quyền mở rộng.

Toàn bộ endpoint mới nằm trong blueprint riêng, không đổi hành vi 4 endpoint lõi và
không thêm gì vào allowlist của `gate`. Mỗi route vẫn đi qua đủ các lớp:
gate (401) → guard (403/404) → service (kiểm tra lại quyền) → schema (400) → lỗi JSON.
"""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import schemas, services
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("extended", __name__)


@bp.get("/courses")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_courses() -> Any:
    return jsonify(services.list_courses(g.actor))


@bp.get("/courses/<course_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def course_detail(course_id: str) -> Any:
    return jsonify(services.get_course(g.actor, course_id))


@bp.post("/courses/<course_id>/enrollments")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def add_enrollment(course_id: str) -> Any:
    services.authorize_manage(g.actor, course_id)
    student_id = schemas.parse_enrollment_body(request.get_json(silent=True))
    return jsonify(services.enroll_student(g.actor, course_id, student_id)), 201


@bp.delete("/courses/<course_id>/enrollments/<student_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def remove_enrollment(course_id: str, student_id: str) -> Any:
    services.authorize_manage(g.actor, course_id)
    return jsonify(services.unenroll_student(g.actor, course_id, student_id))


@bp.get("/me/grades")
@require_role("STUDENT")
@store_scope
def own_grades() -> Any:
    return jsonify(services.my_grades(g.actor))


@bp.get("/admin/users")
@require_role("ADMIN")
@store_scope
def admin_users() -> Any:
    return jsonify(services.list_users(g.actor))


@bp.patch("/admin/users/<user_id>/role")
@require_role("ADMIN")
@store_scope
def admin_change_role(user_id: str) -> Any:
    role = schemas.parse_role_body(request.get_json(silent=True))
    return jsonify(services.change_role(g.actor, user_id, role))
