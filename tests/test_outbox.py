"""Acceptance tests for pattern #8: transactional outbox.

Each test maps to one risk stated in docs/de-xuat-defensive-pattern.md:
the enrollment and its email event must commit together, delivery is
at-least-once, retries are bounded, and pending work survives a restart.
"""

import re
import time

import pytest

from app import create_app, emailer, outbox
from app import store as store_module

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"


class FakeTransport:
    """Records delivered messages and can fail a number of times first."""

    def __init__(self, failures: int = 0, always_fail: bool = False) -> None:
        self.calls = 0
        self.messages: list[dict[str, str]] = []
        self.failures = failures
        self.always_fail = always_fail

    def __call__(self, config, message) -> None:
        self.calls += 1
        if self.always_fail or self.calls <= self.failures:
            raise RuntimeError("smtp is down")
        self.messages.append(message)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "environment-secret-that-is-long-enough")
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "DATABASE_PATH": str(tmp_path / "lms.sqlite3"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client, email: str, password: str = PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def enroll(client, token: str, course_id: str = "c2"):
    return client.post("/me/enrollments", json={"courseId": course_id}, headers=auth(token))


def rows(app, sql: str, params: tuple = ()):
    return app.extensions["lms_store"]["connection"].execute(sql, params).fetchall()


def event_row(app, event_id: str):
    found = rows(
        app,
        """
        SELECT event_id, type, payload, status, attempts, next_attempt_at,
               sent_at, last_error
          FROM outbox_events WHERE event_id = ?
        """,
        (event_id,),
    )
    return found[0] if found else None


def test_enrollment_and_event_commit_together(app, client):
    transport = FakeTransport(always_fail=True)
    app.config["MAIL_TRANSPORT"] = transport

    token = login(client, "chi.sv@lms.test")
    response = enroll(client, token)
    assert response.status_code == 201
    body = response.get_json()
    assert body["courseId"] == "c2"
    assert body["studentId"] == "u4"
    assert body["score"] == 0.0

    assert rows(app, "SELECT * FROM enrollments WHERE course_id='c2' AND student_id='u4'")
    event = event_row(app, body["outboxEventId"])
    assert event is not None
    assert event[1] == outbox.EVENT_ENROLLMENT_CONFIRMED
    assert event[3] == "PENDING"
    assert event[4] == 0
    assert "Cơ sở dữ liệu" in event[2]  # payload chứa tên khóa học
    assert transport.calls == 0  # chưa gửi gì trong request

    sent = outbox.drain_once(app.extensions["lms_store"], app.config)
    assert sent == 0
    assert transport.calls == 1
    event = event_row(app, body["outboxEventId"])
    assert event[3] == "PENDING"
    assert event[4] == 1
    assert "smtp is down" in event[7]
    # dữ liệu đăng ký vẫn còn nguyên dù email lỗi
    assert rows(app, "SELECT 1 FROM enrollments WHERE student_id='u4' AND course_id='c2'")


def test_duplicate_enrollment_is_rejected_without_second_event(app, client):
    app.config["MAIL_TRANSPORT"] = FakeTransport()
    token = login(client, "chi.sv@lms.test")

    assert enroll(client, token).status_code == 201
    duplicate = enroll(client, token)
    assert duplicate.status_code == 409
    assert duplicate.get_json() == {"error": "CONFLICT"}

    events = rows(app, "SELECT event_id FROM outbox_events")
    assert len(events) == 1


def test_retry_sends_exactly_one_email_after_transient_failure(app, client):
    transport = FakeTransport(failures=1)
    app.config["MAIL_TRANSPORT"] = transport
    state = app.extensions["lms_store"]

    token = login(client, "chi.sv@lms.test")
    response = enroll(client, token)
    event_id = response.get_json()["outboxEventId"]
    base = time.time()

    assert outbox.drain_once(state, app.config, now=base) == 0
    assert event_row(app, event_id)[3] == "PENDING"

    # chưa tới hạn thử lại
    assert outbox.drain_once(state, app.config, now=base + 0.1) == 0
    assert transport.calls == 1

    assert outbox.drain_once(state, app.config, now=base + 5) == 1
    assert transport.calls == 2
    assert len(transport.messages) == 1
    message = transport.messages[0]
    assert message["to"] == "chi.sv@lms.test"
    assert "Xác nhận đăng ký khóa học" in message["subject"]
    assert message["eventId"] == event_id

    event = event_row(app, event_id)
    assert event[3] == "SENT"
    assert event[5] is not None  # sent_at


def test_event_goes_dead_after_max_attempts(app, client):
    transport = FakeTransport(always_fail=True)
    app.config["MAIL_TRANSPORT"] = transport
    app.config["OUTBOX_MAX_ATTEMPTS"] = 3
    state = app.extensions["lms_store"]

    token = login(client, "chi.sv@lms.test")
    event_id = enroll(client, token).get_json()["outboxEventId"]
    base = time.time()

    for attempt in range(3):
        outbox.drain_once(state, app.config, now=base + attempt * 10)

    event = event_row(app, event_id)
    assert event[3] == "DEAD"
    assert event[4] == 3
    assert "smtp is down" in event[7]
    assert transport.calls == 3
    # không gửi thêm sau khi đã DEAD
    assert outbox.drain_once(state, app.config, now=base + 100) == 0
    assert transport.calls == 3


def test_drain_is_idempotent_once_sent(app, client):
    transport = FakeTransport()
    app.config["MAIL_TRANSPORT"] = transport
    state = app.extensions["lms_store"]

    token = login(client, "chi.sv@lms.test")
    enroll(client, token)
    now = time.time()

    assert outbox.drain_once(state, app.config, now=now) == 1
    assert outbox.drain_once(state, app.config, now=now + 1) == 0
    assert len(transport.messages) == 1


def test_crashed_claim_is_recovered_after_lease(app, client):
    transport = FakeTransport()
    app.config["MAIL_TRANSPORT"] = transport
    app.config["OUTBOX_LEASE_SECONDS"] = 30
    state = app.extensions["lms_store"]

    token = login(client, "chi.sv@lms.test")
    event_id = enroll(client, token).get_json()["outboxEventId"]
    now = time.time()

    # worker chết sau khi claim, trước khi gửi
    claimed = store_module.claim_outbox_batch(state, now, 10, 30)
    assert [event["eventId"] for event in claimed] == [event_id]
    assert event_row(app, event_id)[3] == "SENDING"

    # hết lease -> được trả về PENDING và gửi lại
    assert outbox.drain_once(state, app.config, now=now + 31) == 1
    assert event_row(app, event_id)[3] == "SENT"


def test_pending_events_survive_process_restart(tmp_path):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        "DATABASE_PATH": str(tmp_path / "shared.sqlite3"),
    }
    first = create_app(config)
    client = first.test_client()
    first.config["MAIL_TRANSPORT"] = FakeTransport(always_fail=True)
    token = login(client, "chi.sv@lms.test")
    event_id = enroll(client, token).get_json()["outboxEventId"]
    outbox.drain_once(first.extensions["lms_store"], first.config)  # lỗi, vẫn PENDING

    second = create_app(config)
    transport = FakeTransport()
    second.config["MAIL_TRANSPORT"] = transport
    assert (
        outbox.drain_once(second.extensions["lms_store"], second.config, now=time.time() + 10) == 1
    )
    assert len(transport.messages) == 1
    assert event_row(second, event_id)[3] == "SENT"


def test_only_students_can_enroll(app, client):
    app.config["MAIL_TRANSPORT"] = FakeTransport()

    instructor = login(client, "an.gv@lms.test")
    assert enroll(client, instructor).status_code == 403

    admin = login(client, "admin@lms.test")
    assert enroll(client, admin).status_code == 403

    student = login(client, "chi.sv@lms.test")
    missing = enroll(client, student, course_id="nope")
    assert missing.status_code == 404
    assert rows(app, "SELECT event_id FROM outbox_events") == []
    assert rows(app, "SELECT 1 FROM enrollments WHERE course_id='nope'") == []


def test_enrollment_requires_authentication(client):
    assert client.post("/me/enrollments", json={"courseId": "c1"}).status_code == 401


def test_confirmation_email_sets_stable_message_id(monkeypatch):
    captured = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, message):
            captured.append(message)

    monkeypatch.setattr(emailer.smtplib, "SMTP", FakeSMTP)
    emailer.send_email(
        {"SMTP_HOST": "smtp.test", "SMTP_FROM": "noreply@lms.test"},
        "chi.sv@lms.test",
        "Xác nhận đăng ký khóa học",
        "Nội dung",
        event_id="event-abc",
    )
    assert len(captured) == 1
    assert captured[0]["Message-ID"] == "<event-abc@lms.local>"
    assert captured[0]["To"] == "chi.sv@lms.test"


def test_web_enroll_form_creates_event(app, client):
    app.config["MAIL_TRANSPORT"] = FakeTransport()
    login_page = client.get("/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', login_page.get_data(as_text=True)).group(
        1
    )
    logged_in = client.post(
        "/login",
        data={"csrf_token": csrf, "email": "chi.sv@lms.test", "password": PASSWORD},
    )
    assert logged_in.status_code == 302

    account = client.get("/account")
    html = account.get_data(as_text=True)
    assert "/courses/c2/enroll" in html
    form_token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    missing_csrf = client.post("/courses/c2/enroll", data={})
    assert missing_csrf.status_code == 400

    enrolled = client.post("/courses/c2/enroll", data={"csrf_token": form_token})
    assert enrolled.status_code == 302
    assert enrolled.headers["Location"].endswith("/account")
    assert rows(app, "SELECT 1 FROM outbox_events") == [(1,)]
    assert rows(app, "SELECT 1 FROM enrollments WHERE course_id='c2' AND student_id='u4'") == [(1,)]


def test_cli_drain_command(app, client):
    transport = FakeTransport()
    app.config["MAIL_TRANSPORT"] = transport
    token = login(client, "chi.sv@lms.test")
    enroll(client, token)

    result = app.test_cli_runner().invoke(args=["outbox", "drain"])
    assert result.exit_code == 0
    assert "delivered=1" in result.output
    assert len(transport.messages) == 1

    status = app.test_cli_runner().invoke(args=["outbox", "status"])
    assert status.exit_code == 0
    assert "SENT=1" in status.output


def test_settings_fall_back_to_defaults_for_invalid_values():
    defaults = outbox.settings({})
    assert defaults["max_attempts"] == 5
    assert defaults["retry_delay"] == 2.0
    assert defaults["batch_size"] == 10
    assert defaults["poll_interval"] == 0.0

    parsed = outbox.settings(
        {
            "OUTBOX_MAX_ATTEMPTS": "không-phải-số",
            "OUTBOX_RETRY_DELAY_SECONDS": "-3",
            "OUTBOX_BATCH_SIZE": True,
            "OUTBOX_POLL_INTERVAL": "0",
        }
    )
    assert parsed["max_attempts"] == 5
    assert parsed["retry_delay"] == 2.0
    assert parsed["batch_size"] == 10
    assert parsed["poll_interval"] == 0.0

    custom = outbox.settings(
        {
            "OUTBOX_MAX_ATTEMPTS": 2,
            "OUTBOX_RETRY_DELAY_SECONDS": 0.5,
            "OUTBOX_LEASE_SECONDS": 5,
            "OUTBOX_BATCH_SIZE": 3,
            "OUTBOX_POLL_INTERVAL": 1.5,
        }
    )
    assert custom == {
        "max_attempts": 2,
        "retry_delay": 0.5,
        "lease_seconds": 5.0,
        "batch_size": 3,
        "poll_interval": 1.5,
    }


def test_start_worker_is_disabled_in_tests(app):
    assert outbox.start_worker(app) is None


def test_default_transport_delegates_to_emailer(app, monkeypatch):
    calls = []
    monkeypatch.setattr(
        outbox.emailer,
        "send_email",
        lambda config, to, subject, body, event_id=None: calls.append(
            (to, subject, body, event_id)
        ),
    )
    message = outbox.build_message(
        {
            "eventId": "evt-1",
            "payload": {
                "courseName": "Cơ sở dữ liệu",
                "courseId": "c2",
                "studentEmail": "sv@lms.test",
                "studentName": "",
            },
        }
    )
    outbox.default_transport(app.config, message)

    to, subject, body, event_id = calls[0]
    assert to == "sv@lms.test"
    assert event_id == "evt-1"
    assert "Cơ sở dữ liệu" in subject
    assert "Chào bạn" in body
    assert "c2" in body
