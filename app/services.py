"""Layer 4 - object-level authorisation. No flask imports; independent of layer 3."""
import math

from . import audit, store
from .errors import Forbidden, NotFound, ValidationError


def _check_actor(actor):
    if (
        not isinstance(actor, dict)
        or not isinstance(actor.get("id"), str)
        or not isinstance(actor.get("role"), str)
    ):
        raise Forbidden()
    return actor


def get_course(course_id):
    course = store.current().get_course(course_id)
    if course is None:
        raise NotFound()
    return course


def _check_score(score):
    """Layer 5 re-check at the service boundary."""
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not math.isfinite(score)
        or score < 0
        or score > 10
    ):
        raise ValidationError()


def get_grades(actor, course_id):
    actor = _check_actor(actor)
    course = get_course(course_id)
    state = store.current()
    with state.lock:
        rows = state.course_enrollments(course["id"])
        role = actor["role"]
        if role == "ADMIN" or (
            role == "INSTRUCTOR" and course["instructorId"] == actor["id"]
        ):
            visible = rows
        elif role == "STUDENT":
            visible = [r for r in rows if r["studentId"] == actor["id"]]
            if not visible:  # not enrolled
                raise Forbidden()
        else:
            raise Forbidden()
        return [{"studentId": r["studentId"], "score": r["score"]} for r in visible]


def authorize_update_grade(actor, course_id):
    """Only the instructor who teaches the course may edit grades."""
    actor = _check_actor(actor)
    course = get_course(course_id)
    if actor["role"] != "INSTRUCTOR" or course["instructorId"] != actor["id"]:
        raise Forbidden()
    return course


def update_grade(actor, course_id, student_id, score):
    authorize_update_grade(actor, course_id)  # 404 course -> 403
    _check_score(score)  # 400
    state = store.current()
    with state.lock:
        enrollment = state.find_enrollment(course_id, student_id)
        if enrollment is None:  # 404 enrollment
            raise NotFound()
        old = enrollment["score"]
        enrollment["score"] = score
    audit.get().log(
        actor_id=actor["id"],
        action="UPDATE_GRADE",
        resource=f"courses/{course_id}/grades/{student_id}",
        result="SUCCESS",
        oldScore=old,
        newScore=score,
    )
    return {"courseId": course_id, "studentId": student_id, "score": score}
