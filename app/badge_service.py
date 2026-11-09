"""Huy hiệu và chuỗi ngày hoạt động (streak)."""

from datetime import date, timedelta
from typing import Any

from . import audit
from . import store as store_module
from .errors import Forbidden, NotFound, ValidationError
from .runtime import current_store

DEFAULT_BADGES = [
    ("Bài học đầu tiên", "Hoàn thành bài học đầu tiên"),
    ("Siêng năng", "Hoàn thành 5 bài học"),
    ("Cao thủ quiz", "Đạt điểm 9 trở lên trong một bài kiểm tra"),
]


def _role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def ensure_defaults(state: dict[str, Any]) -> None:
    existing = {badge["name"] for badge in store_module.list_badges(state)}
    for name, description in DEFAULT_BADGES:
        if name not in existing:
            store_module.create_badge(state, name=name, description=description, now=state["now"]())


def check_auto(state: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    """Trao huy hiệu tự động dựa trên hoạt động học tập."""
    ensure_defaults(state)
    awarded: list[dict[str, Any]] = []
    lessons = store_module.count_completed_lessons(state, user_id)
    best_score = store_module.max_quiz_score(state, user_id)
    rules = [
        ("Bài học đầu tiên", lessons >= 1),
        ("Siêng năng", lessons >= 5),
        ("Cao thủ quiz", best_score is not None and best_score >= 9.0),
    ]
    for name, matched in rules:
        if not matched or store_module.user_has_badge_name(state, user_id, name):
            continue
        badge = store_module.find_badge_by_name(state, name)
        if badge is not None and store_module.award_badge(
            state, user_id=user_id, badge_id=badge["id"], now=state["now"]()
        ):
            awarded.append(badge)
    return awarded


def list_badges(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        ensure_defaults(state)
        return store_module.list_badges(state)


def create_badge(actor: dict[str, Any], name: str, description: str) -> dict[str, Any]:
    if _role(actor) != "ADMIN":
        raise Forbidden()
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ValidationError()
    state = current_store()
    with state["lock"]:
        badge = store_module.create_badge(
            state, name=name.strip(), description=description or "", now=state["now"]()
        )
        audit.record(
            actor["id"],
            "BADGE_CREATE",
            "/admin/badges",
            "OK",
            badgeId=badge["id"],
            path=state["audit_log_path"],
        )
        return badge


def award(actor: dict[str, Any], badge_id: str, user_id: str) -> dict[str, Any]:
    if _role(actor) != "ADMIN":
        raise Forbidden()
    state = current_store()
    with state["lock"]:
        badge = store_module.get_badge(state, badge_id)
        if badge is None:
            raise NotFound()
        if user_id not in state["users"]:
            raise NotFound()
        store_module.award_badge(state, user_id=user_id, badge_id=badge_id, now=state["now"]())
        return {"badgeId": badge_id, "userId": user_id, "awarded": True}


def my_badges(actor: dict[str, Any]) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        return store_module.list_user_badges(state, str(actor.get("id")))


def streak(actor: dict[str, Any]) -> int:
    state = current_store()
    with state["lock"]:
        days = store_module.list_activity_days(state, str(actor.get("id")))
    if not days:
        return 0
    known = set(days)
    current = date.today()
    if current.isoformat() not in known and (current - timedelta(days=1)).isoformat() not in known:
        return 0
    count = 0
    cursor = current if current.isoformat() in known else current - timedelta(days=1)
    while cursor.isoformat() in known:
        count += 1
        cursor -= timedelta(days=1)
    return count
