"""Layer 5 - strict input validation."""
import math

from .errors import ValidationError


def validate_login_body(data):
    if not isinstance(data, dict) or set(data) != {"email", "password"}:
        raise ValidationError()
    email, password = data["email"], data["password"]
    if not isinstance(email, str) or not isinstance(password, str):
        raise ValidationError()
    return email, password


def validate_grade_body(data):
    if not isinstance(data, dict) or set(data) != {"score"}:  # no extra / missing fields
        raise ValidationError()
    score = data["score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)):  # rejects "10", true
        raise ValidationError()
    if not math.isfinite(score) or score < 0 or score > 10:
        raise ValidationError()
    return score
