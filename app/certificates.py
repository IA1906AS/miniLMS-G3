"""Endpoint chứng chỉ, bảng xếp hạng và huy hiệu."""

from typing import Any

from flask import Blueprint, g, jsonify, request

from . import badge_service, certificate_service
from .guards import require_role
from .scoped import store_scope

bp = Blueprint("certificates", __name__)


@bp.get("/me/certificates")
@require_role("STUDENT")
@store_scope
def my_certificates() -> Any:
    return jsonify(certificate_service.my_certificates(g.actor))


@bp.get("/certificates/<certificate_id>")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def certificate_detail(certificate_id: str) -> Any:
    return jsonify(certificate_service.certificate_data(g.actor, certificate_id))


@bp.get("/courses/<course_id>/certificates")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def course_certificates(course_id: str) -> Any:
    return jsonify(certificate_service.list_course(g.actor, course_id))


@bp.post("/courses/<course_id>/certificates")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def issue_certificate(course_id: str) -> Any:
    payload = request.get_json(silent=True) or {}
    return jsonify(
        certificate_service.issue(g.actor, course_id, str(payload.get("studentId") or ""))
    ), 201


@bp.post("/courses/<course_id>/certificate-rule")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def set_certificate_rule(course_id: str) -> Any:
    payload = request.get_json(silent=True) or {}
    return jsonify(
        certificate_service.set_rule(
            g.actor,
            course_id,
            payload.get("minGrade"),
            payload.get("requireLessons", True),
        )
    )


@bp.delete("/certificates/<certificate_id>")
@require_role("ADMIN", "INSTRUCTOR")
@store_scope
def revoke_certificate(certificate_id: str) -> Any:
    return jsonify(certificate_service.revoke(g.actor, certificate_id))


@bp.get("/courses/<course_id>/leaderboard")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def leaderboard(course_id: str) -> Any:
    return jsonify(certificate_service.course_leaderboard(g.actor, course_id))


@bp.get("/me/badges")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def my_badges() -> Any:
    return jsonify(badge_service.my_badges(g.actor))


@bp.get("/badges")
@require_role("ADMIN", "INSTRUCTOR", "STUDENT")
@store_scope
def list_badges() -> Any:
    return jsonify(badge_service.list_badges(g.actor))


@bp.post("/admin/badges")
@require_role("ADMIN")
@store_scope
def create_badge() -> Any:
    payload = request.get_json(silent=True) or {}
    return jsonify(
        badge_service.create_badge(
            g.actor,
            str(payload.get("name") or ""),
            str(payload.get("description") or ""),
        )
    ), 201


@bp.post("/admin/badges/<badge_id>/award")
@require_role("ADMIN")
@store_scope
def award_badge(badge_id: str) -> Any:
    payload = request.get_json(silent=True) or {}
    return jsonify(badge_service.award(g.actor, badge_id, str(payload.get("userId") or "")))
