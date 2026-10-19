import math
from typing import Any

from .errors import ValidationError


def parse_login_body(body: Any) -> tuple[str, str]:
    if (
        not isinstance(body, dict)
        or set(body) != {"email", "password"}
        or not isinstance(body["email"], str)
        or not isinstance(body["password"], str)
    ):
        raise ValidationError()
    return body["email"], body["password"]


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
