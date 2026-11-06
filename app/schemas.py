import math
import re
from datetime import UTC, datetime
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


PROFILE_FIELDS = frozenset({"fullName", "bio", "phone"})


def parse_profile_update_body(body: Any) -> dict[str, str]:
    """Chỉ cho sửa fullName/bio/phone; field khác (role, email, id...) là 400."""
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
    if "phone" in body:
        phone = body["phone"]
        if not isinstance(phone, str) or len(phone) > 30:
            raise ValidationError()
        updates["phone"] = phone
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


def parse_course_update_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"name"}:
        raise ValidationError()
    return validate_course_name(body["name"])


def parse_audit_limit(raw: str | None) -> int:
    if raw is None:
        return 100
    if not isinstance(raw, str) or not raw.isdigit():
        raise ValidationError()
    limit = int(raw)
    if not 1 <= limit <= 1000:
        raise ValidationError()
    return limit


def parse_due_at(value: Any) -> float:
    """Chấp nhận epoch giây hoặc chuỗi ISO-8601 (có/không có 'Z')."""
    if isinstance(value, bool):
        raise ValidationError()
    if isinstance(value, (int, float)):
        due = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as error:
            raise ValidationError() from error
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        due = parsed.timestamp()
    else:
        raise ValidationError()
    if not math.isfinite(due):
        raise ValidationError()
    return due


def parse_assignment_body(body: Any) -> tuple[str, str, float]:
    if not isinstance(body, dict) or not {"title", "dueAt"} <= set(body):
        raise ValidationError()
    if not set(body) <= {"title", "description", "dueAt"}:
        raise ValidationError()
    title = body["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise ValidationError()
    description = body.get("description", "")
    if not isinstance(description, str) or len(description) > 2000:
        raise ValidationError()
    return title.strip(), description, parse_due_at(body["dueAt"])


def parse_submission_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"content"}:
        raise ValidationError()
    content = body["content"]
    if not isinstance(content, str) or not content.strip() or len(content) > 5000:
        raise ValidationError()
    return content


def _parse_text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError()
    return value


def parse_announcement_body(body: Any) -> tuple[str, str]:
    if not isinstance(body, dict) or set(body) != {"title", "body"}:
        raise ValidationError()
    return _parse_text(body["title"], 200), _parse_text(body["body"], 5000)


def parse_thread_body(body: Any) -> tuple[str, str]:
    if not isinstance(body, dict) or set(body) != {"title", "body"}:
        raise ValidationError()
    return _parse_text(body["title"], 200), _parse_text(body["body"], 5000)


def parse_comment_body(body: Any) -> str:
    if not isinstance(body, dict) or set(body) != {"body"}:
        raise ValidationError()
    return _parse_text(body["body"], 2000)


def parse_grade_submission_body(body: Any) -> tuple[float, str]:
    if (
        not isinstance(body, dict)
        or not {"grade"} <= set(body)
        or not set(body) <= {"grade", "feedback"}
    ):
        raise ValidationError()
    grade = float(validate_score(body["grade"]))
    feedback = body.get("feedback", "")
    if not isinstance(feedback, str) or len(feedback) > 2000:
        raise ValidationError()
    return grade, feedback


def parse_quiz_body(body: Any) -> tuple[str, str, int, int, list[dict[str, Any]]]:
    if (
        not isinstance(body, dict)
        or not {"title", "durationMinutes", "questions"} <= set(body)
        or not set(body) <= {"title", "description", "durationMinutes", "maxAttempts", "questions"}
    ):
        raise ValidationError()

    title = _parse_text(body["title"], 200)
    description = body.get("description", "")
    if not isinstance(description, str) or len(description) > 2000:
        raise ValidationError()

    duration = body["durationMinutes"]
    if isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0 or duration > 300:
        raise ValidationError()

    max_attempts = body.get("maxAttempts", 1)
    if (
        isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or max_attempts <= 0
        or max_attempts > 100
    ):
        raise ValidationError()

    raw_questions = body["questions"]
    if not isinstance(raw_questions, list) or len(raw_questions) == 0 or len(raw_questions) > 100:
        raise ValidationError()

    questions = []
    for q in raw_questions:
        if (
            not isinstance(q, dict)
            or not {"question", "options", "correctOption"} <= set(q)
            or not set(q) <= {"question", "options", "correctOption", "points"}
        ):
            raise ValidationError()
        q_text = _parse_text(q["question"], 1000)
        options = q["options"]
        if not isinstance(options, list) or len(options) < 2 or len(options) > 10:
            raise ValidationError()
        clean_options = []
        for opt in options:
            if not isinstance(opt, str) or not opt.strip() or len(opt) > 500:
                raise ValidationError()
            clean_options.append(opt.strip())
        correct = q["correctOption"]
        if isinstance(correct, bool) or not isinstance(correct, int) or not (0 <= correct < len(clean_options)):
            raise ValidationError()
        points = float(q.get("points", 1.0))
        if points <= 0:
            raise ValidationError()
        questions.append(
            {
                "question": q_text,
                "options": clean_options,
                "correctOption": correct,
                "points": points,
            }
        )

    return title, description, duration, max_attempts, questions


def parse_quiz_submit_body(body: Any) -> dict[str, int]:
    if not isinstance(body, dict) or set(body) != {"answers"} or not isinstance(body["answers"], dict):
        raise ValidationError()
    answers = {}
    for q_id, opt in body["answers"].items():
        if not isinstance(q_id, str) or isinstance(opt, bool) or not isinstance(opt, int) or opt < 0:
            raise ValidationError()
        answers[q_id] = opt
    return answers


def parse_grade_v2_body(body: Any) -> tuple[int | float, int]:
    if not isinstance(body, dict) or set(body) != {"score", "expectedVersion"}:
        raise ValidationError()
    expected = body["expectedVersion"]
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise ValidationError()
    return validate_score(body["score"]), expected
