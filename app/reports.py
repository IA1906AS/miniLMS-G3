"""Endpoint báo cáo tiến độ/điểm số."""

from typing import Any

from flask import Blueprint, g, jsonify

from . import report_service
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("reports", __name__)


@bp.get("/courses/<course_id>/report")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def course_report(course_id: str) -> Any:
    return jsonify(report_service.course_report(g.actor, course_id))


@bp.get("/me/progress")
@require_role("STUDENT")
@store_scope
def my_progress() -> Any:
    return jsonify(report_service.student_progress(g.actor))


@bp.get("/admin/report")
@require_role("ADMIN")
@store_scope
def admin_report() -> Any:
    return jsonify(report_service.system_report(g.actor))
