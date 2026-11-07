"""Bản Before của pattern #8: email xác nhận gửi ngay trong request, chưa có outbox."""

import os
import re

import pytest

from app import create_app, emailer

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "environment-secret-that-is-long-enough")
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
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


def test_confirmation_email_is_sent_inside_request(app, client, monkeypatch):
    sent: list[tuple[str, str, str]] = []

    def fake_send(config, recipient, subject, body, *, event_id=None):
        sent.append((recipient, subject, body))

    monkeypatch.setattr(emailer, "send_email", fake_send)

    token = login(client, "chi.sv@lms.test")
    response = enroll(client, token)
    assert response.status_code == 201
    assert response.get_json() == {"courseId": "c2", "studentId": "u4", "score": 0.0}

    assert [item[0] for item in sent] == ["chi.sv@lms.test"]
    assert "Xác nhận đăng ký khóa học" in sent[0][1]
    assert rows(app, "SELECT 1 FROM enrollments WHERE course_id='c2' AND student_id='u4'") == [(1,)]
    # Bản Before không tạo sự kiện nào trong outbox
    assert rows(app, "SELECT 1 FROM outbox_events") == []


def test_smtp_failure_loses_email_but_keeps_enrollment(app, client, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("smtp is down")

    monkeypatch.setattr(emailer, "send_email", boom)

    token = login(client, "chi.sv@lms.test")
    response = enroll(client, token)
    # Request trả 500 sau khi enrollment đã commit: mail mất nhưng dữ liệu vẫn còn
    assert response.status_code == 500
    assert response.get_json() == {"error": "INTERNAL_ERROR"}

    # Enrollment đã commit trước khi gửi mail nên dữ liệu vẫn còn...
    assert rows(app, "SELECT 1 FROM enrollments WHERE course_id='c2' AND student_id='u4'") == [(1,)]
    # ...nhưng email đã mất, không có bản ghi nào để gửi lại
    assert rows(app, "SELECT 1 FROM outbox_events") == []
    # Đăng ký lại để nhận mail thì bị chặn vì đã ghi danh
    assert enroll(client, token).status_code == 409


def test_duplicate_enrollment_is_conflict(app, client, monkeypatch):
    monkeypatch.setattr(emailer, "send_email", lambda *args, **kwargs: None)

    token = login(client, "chi.sv@lms.test")
    assert enroll(client, token).status_code == 201
    duplicate = enroll(client, token)
    assert duplicate.status_code == 409
    assert duplicate.get_json() == {"error": "CONFLICT"}


def test_only_students_can_enroll(client, monkeypatch):
    monkeypatch.setattr(emailer, "send_email", lambda *args, **kwargs: None)

    instructor = login(client, "an.gv@lms.test")
    assert enroll(client, instructor).status_code == 403

    admin = login(client, "admin@lms.test")
    assert enroll(client, admin).status_code == 403


def test_missing_course_is_404(app, client, monkeypatch):
    monkeypatch.setattr(emailer, "send_email", lambda *args, **kwargs: None)

    token = login(client, "chi.sv@lms.test")
    assert enroll(client, token, course_id="nope").status_code == 404
    assert rows(app, "SELECT 1 FROM enrollments WHERE course_id='nope'") == []


def test_enrollment_requires_authentication(client):
    assert client.post("/me/enrollments", json={"courseId": "c1"}).status_code == 401


def test_web_enroll_form_sends_email(app, client, monkeypatch):
    sent: list[str] = []

    def fake_send(config, recipient, subject, body, *, event_id=None):
        sent.append(recipient)

    monkeypatch.setattr(emailer, "send_email", fake_send)

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
    assert sent == ["chi.sv@lms.test"]
    assert rows(app, "SELECT 1 FROM enrollments WHERE course_id='c2' AND student_id='u4'") == [(1,)]
