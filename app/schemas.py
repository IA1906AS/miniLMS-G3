import math
import re
from typing import Any

from .errors import ValidationError


def parse_login_body(body: Any) -> tuple[str, str]:
    if (
        not isinstance(body, dict)
        or set(body) not in ({"email", "password"}, {"email", "password", "remember"})
        or not isinstance(body["email"], str)
        or not isinstance(body["password"], str)
        or ("remember" in body and not isinstance(body["remember"], bool))
    ):
        raise ValidationError()
    return body["email"], body["password"]


def validate_auth_password(password: str) -> bool:
    return (
        len(password) >= 10
        and len(password.encode("utf-8")) <= 72
        and any(char.isupper() for char in password)
        and any(char.islower() for char in password)
        and any(char.isdigit() for char in password)
    )


def parse_register_body(body: Any) -> tuple[str, str, str]:
    allowed_fields = {"email", "name", "password"}
    if isinstance(body, dict) and "termsAccepted" in body:
        allowed_fields.add("termsAccepted")
    if (
        not isinstance(body, dict)
        or set(body) != allowed_fields
        or not all(isinstance(body[field], str) for field in ("email", "name", "password"))
        or ("termsAccepted" in body and body["termsAccepted"] is not True)
    ):
        raise ValidationError()
    email = body["email"].strip().lower()
    name = body["name"].strip()
    password = body["password"]
    if (
        len(email) > 254
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
        or not name
        or len(name) > 100
        or not validate_auth_password(password)
    ):
        raise ValidationError()
    return email, name, password


def parse_password_reset_request(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"email"} or not isinstance(body["email"], str):
        raise ValidationError()
    email = body["email"].strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValidationError()
    return email


def parse_password_reset_confirmation(body: Any) -> tuple[str, str]:
    if (
        not isinstance(body, dict)
        or set(body) != {"token", "password"}
        or not isinstance(body["token"], str)
        or not isinstance(body["password"], str)
        or not body["token"]
        or not validate_auth_password(body["password"])
    ):
        raise ValidationError()
    return body["token"], body["password"]


def validate_score(score: Any) -> int | float:
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValidationError()
    try:
        valid = math.isfinite(score) and 0 <= score <= 10
    except OverflowError as error:
        raise ValidationError() from error
    if not valid:
        raise ValidationError()
    return score


def validate_grade_body(body: Any) -> int | float:
    if not isinstance(body, dict) or set(body) != {"score"}:
        raise ValidationError()
    return validate_score(body["score"])


def parse_score_body(body: Any) -> int | float:
    return validate_grade_body(body)


VALID_ROLES = frozenset({"ADMIN", "INSTRUCTOR", "STUDENT"})


def parse_self_enrollment_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"courseId"}:
        raise ValidationError()
    course_id = body["courseId"]
    if not isinstance(course_id, str) or not course_id.strip() or len(course_id) > 100:
        raise ValidationError()
    return course_id


def parse_enrollment_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"studentId"}:
        raise ValidationError()
    student_id = body["studentId"]
    if not isinstance(student_id, str) or not student_id.strip() or len(student_id) > 100:
        raise ValidationError()
    return student_id


def parse_role_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"role"}:
        raise ValidationError()
    role = body["role"]
    if not isinstance(role, str) or role not in VALID_ROLES:
        raise ValidationError()
    return role


def validate_new_password(password: str) -> bool:
    """Mật khẩu mới: >= 10 ký tự, có chữ và có số, không vượt giới hạn bcrypt."""
    return (
        isinstance(password, str)
        and len(password) >= 10
        and len(password.encode("utf-8")) <= 72
        and any(char.isalpha() for char in password)
        and any(char.isdigit() for char in password)
    )


def parse_password_change_body(body: Any) -> tuple[str, str]:
    if not isinstance(body, dict) or set(body) != {"oldPassword", "newPassword"}:
        raise ValidationError()
    old_password = body["oldPassword"]
    new_password = body["newPassword"]
    if not isinstance(old_password, str) or not isinstance(new_password, str):
        raise ValidationError()
    if not validate_new_password(new_password):
        raise ValidationError()
    return old_password, new_password


PROFILE_FIELDS = frozenset({"fullName", "bio"})


def parse_profile_update_body(body: Any) -> dict[str, str]:
    """Chỉ cho sửa fullName/bio; field khác (role, email, id...) là 400."""
    if not isinstance(body, dict) or not body or not set(body) <= PROFILE_FIELDS:
        raise ValidationError()
    updates: dict[str, str] = {}
    if "fullName" in body:
        full_name = body["fullName"]
        if not isinstance(full_name, str) or len(full_name) > 100:
            raise ValidationError()
        updates["fullName"] = full_name
    if "bio" in body:
        bio = body["bio"]
        if not isinstance(bio, str) or len(bio) > 500:
            raise ValidationError()
        updates["bio"] = bio
    return updates


def validate_course_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValidationError()
    return name.strip()


def parse_course_body(body: Any) -> tuple[str, str]:
    if not isinstance(body, dict) or set(body) != {"name", "instructorId"}:
        raise ValidationError()
    instructor_id = body["instructorId"]
    if not isinstance(instructor_id, str) or not instructor_id.strip():
        raise ValidationError()
    return validate_course_name(body["name"]), instructor_id


def parse_course_request_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"name"}:
        raise ValidationError()
    return validate_course_name(body["name"])
