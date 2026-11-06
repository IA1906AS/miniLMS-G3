"""Transactional outbox for LMS domain events.

The business row (an enrollment) and the event row are written in the same
SQLite transaction, so an event can never be lost between the two writes.
A dispatcher drains the table and delivers each event at least once.

The retry delay is deliberately fixed: exponential backoff with jitter is a
separate pattern (#1) and must not be mixed into this one.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any

from . import audit, emailer, store

EVENT_ENROLLMENT_CONFIRMED = "enrollment.confirmed"

Message = dict[str, str]
Transport = Callable[[Mapping[str, Any], Message], None]


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def settings(config: Mapping[str, Any]) -> dict[str, Any]:
    poll_interval = _as_float(config.get("OUTBOX_POLL_INTERVAL"), 0.0)
    return {
        "max_attempts": _as_int(config.get("OUTBOX_MAX_ATTEMPTS"), 5),
        "retry_delay": _as_float(config.get("OUTBOX_RETRY_DELAY_SECONDS"), 2.0),
        "lease_seconds": _as_float(config.get("OUTBOX_LEASE_SECONDS"), 60.0),
        "batch_size": _as_int(config.get("OUTBOX_BATCH_SIZE"), 10),
        "poll_interval": poll_interval if poll_interval > 0 else 0.0,
    }


def new_event(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "eventId": secrets.token_urlsafe(16),
        "type": event_type,
        "payload": dict(payload),
    }


def enrollment_confirmation_payload(
    *,
    student_id: str,
    student_email: str,
    student_name: str,
    course_id: str,
    course_name: str,
) -> dict[str, str]:
    return {
        "studentId": student_id,
        "studentEmail": student_email,
        "studentName": student_name,
        "courseId": course_id,
        "courseName": course_name,
    }


def build_message(event: Mapping[str, Any]) -> Message:
    payload = event["payload"]
    if event.get("type") == "announcement.posted":
        return {
            "to": str(payload.get("to", "")),
            "subject": str(payload.get("subject", "")),
            "body": str(payload.get("body", "")),
            "eventId": str(event["eventId"]),
        }
    course_name = str(payload.get("courseName", ""))
    student_name = str(payload.get("studentName") or "").strip()
    greeting = f"Chào {student_name}," if student_name else "Chào bạn,"
    body = (
        f"{greeting}\n\n"
        f'Bạn đã đăng ký thành công khóa học "{course_name}" '
        f"(mã khóa học: {payload.get('courseId', '')}).\n"
        "Điểm của bạn hiện là 0.0 và sẽ được giảng viên cập nhật trong khóa học.\n\n"
        "Nếu bạn không thực hiện đăng ký này, hãy liên hệ quản trị viên.\n"
    )
    return {
        "to": str(payload.get("studentEmail", "")),
        "subject": f"Xác nhận đăng ký khóa học {course_name}",
        "body": body,
        "eventId": str(event["eventId"]),
    }


def default_transport(config: Mapping[str, Any], message: Message) -> None:
    emailer.send_email(
        dict(config),
        message["to"],
        message["subject"],
        message["body"],
        event_id=message["eventId"],
    )


def drain_once(
    state: dict[str, Any],
    config: Mapping[str, Any],
    *,
    now: float | None = None,
    limit: int | None = None,
) -> int:
    """Deliver due events once. Returns the number of successfully sent emails."""
    moment = time.time() if now is None else now
    options = settings(config)
    transport: Transport = config.get("MAIL_TRANSPORT") or default_transport
    batch_size = options["batch_size"] if limit is None else max(0, limit)

    with state["lock"]:
        store.recover_expired_outbox(state, moment)
    events = store.claim_outbox_batch(state, moment, batch_size, options["lease_seconds"])

    delivered = 0
    for event in events:
        try:
            transport(config, build_message(event))
        except Exception as error:  # noqa: BLE001 - every transport failure retries
            status = store.mark_outbox_failed(
                state,
                event["eventId"],
                moment,
                f"{type(error).__name__}: {error}"[:500],
                options["max_attempts"],
                options["retry_delay"],
            )
            audit.record(
                None,
                "OUTBOX_DELIVERY_FAILED",
                event["type"],
                status,
                eventId=event["eventId"],
                path=state["audit_log_path"],
            )
        else:
            store.mark_outbox_sent(state, event["eventId"], moment)
            delivered += 1
            audit.record(
                None,
                "OUTBOX_DELIVERED",
                event["type"],
                "OK",
                eventId=event["eventId"],
                path=state["audit_log_path"],
            )
    return delivered


def start_worker(app: Any) -> threading.Thread | None:
    """Start a daemon poller when OUTBOX_POLL_INTERVAL is configured."""
    interval = settings(app.config)["poll_interval"]
    if interval <= 0 or app.config.get("TESTING"):
        return None

    state = app.extensions["lms_store"]

    def poll() -> None:
        while True:
            try:
                with app.app_context():
                    drain_once(state, app.config)
            except Exception:  # noqa: BLE001 - the poller must survive failures
                pass
            time.sleep(interval)

    thread = threading.Thread(target=poll, name="lms-outbox", daemon=True)
    thread.start()
    return thread
