"""Bước 3.6 — optimistic locking cho điểm (endpoint v2).

Endpoint lõi `PUT /courses/<id>/grades/<sid>` giữ nguyên hợp đồng; v2 yêu cầu
`expectedVersion` và trả 409 khi version đã đổi. Không import Flask.
"""

from typing import Any

from . import audit, schemas, services
from . import store as store_module
from .errors import Conflict, NotFound
from .runtime import current_store


def get_grade(actor: dict[str, Any], course_id: str, student_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        services.authorize_update(actor, course_id)
        row = store_module.read_grade_version(state, course_id, student_id)
        if row is None:
            raise NotFound()
        score, version = row
        return {
            "courseId": course_id,
            "studentId": student_id,
            "score": score,
            "version": version,
        }


def update_grade(
    actor: dict[str, Any],
    course_id: str,
    student_id: str,
    score: int | float,
    expected_version: int,
) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        services.authorize_update(actor, course_id)
        score = schemas.validate_score(score)
        current = store_module.read_grade_version(state, course_id, student_id)
        if current is None:
            raise NotFound()

        old_score = current[0]
        updated, new_version, current_score = store_module.update_grade_if_version(
            state, course_id, student_id, score, expected_version
        )
        if not updated:
            if new_version is None:
                raise NotFound()
            raise Conflict()

        audit.record(
            actor["id"],
            "UPDATE_GRADE",
            f"/courses/{course_id}/grades/{student_id}/v2",
            "OK",
            oldScore=old_score,
            newScore=score,
            version=new_version,
            path=state["audit_log_path"],
        )
        return {
            "courseId": course_id,
            "studentId": student_id,
            "score": score,
            "version": new_version,
        }
