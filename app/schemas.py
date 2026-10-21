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
    if (
        not isinstance(body, dict)
        or set(body) != {"email"}
        or not isinstance(body["email"], str)
    ):
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
