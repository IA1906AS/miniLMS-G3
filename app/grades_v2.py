"""Bước 3.6 — endpoint điểm có optimistic locking (blueprint riêng).

Không đụng vào 4 endpoint lõi; chỉ thêm cặp route `/v2`.
"""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import grade_version_service, schemas, services
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("grades_v2", __name__)


@bp.get("/courses/<course_id>/grades/<student_id>/v2")
@require_role("INSTRUCTOR")
@store_scope
def get_grade_v2(course_id: str, student_id: str) -> Any:
    return jsonify(grade_version_service.get_grade(g.actor, course_id, student_id))


@bp.put("/courses/<course_id>/grades/<student_id>/v2")
@require_role("INSTRUCTOR")
@store_scope
def update_grade_v2(course_id: str, student_id: str) -> Any:
    services.authorize_update(g.actor, course_id)
    score, expected_version = schemas.parse_grade_v2_body(request.get_json(silent=True))
    return jsonify(
        grade_version_service.update_grade(g.actor, course_id, student_id, score, expected_version)
    )
