"""Các luồng HTML: đăng nhập, đăng ký, quên mật khẩu và trang tài khoản."""

import re

import pytest

from app import create_app, emailer

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "DATABASE_PATH": str(tmp_path / "lms.sqlite3"),
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_from(client, path: str) -> str:
    html = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, f"không thấy csrf_token trong {path}"
    return match.group(1)


def login_form(client, email: str, password: str = PASSWORD):
    return client.post(
        "/login",
        data={
            "csrf_token": csrf_from(client, "/login"),
            "email": email,
            "password": password,
        },
    )


def test_login_shows_error_for_wrong_password(client):
    response = login_form(client, "chi.sv@lms.test", "sai-mat-khau")
    assert response.status_code == 401
    assert "không chính xác" in response.get_data(as_text=True)


def test_login_redirects_valid_student_to_account(client):
    response = login_form(client, "chi.sv@lms.test")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/account")


def test_register_rejects_mismatched_confirmation(client):
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf_from(client, "/register"),
            "name": "Nguyen Van A",
            "email": "a@example.com",
            "password": "SecurePass123",
            "confirm_password": "SecurePass124",
            "terms": "on",
        },
    )
    assert response.status_code == 400


def test_register_rejects_existing_email(client):
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf_from(client, "/register"),
            "name": "Chi",
            "email": "chi.sv@lms.test",
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
            "terms": "on",
        },
    )
    assert response.status_code == 409
    assert "đã được đăng ký" in response.get_data(as_text=True)


def test_account_page_for_instructor_and_admin(client):
    login_form(client, "an.gv@lms.test")
    instructor_page = client.get("/account").get_data(as_text=True)
    assert "Lập trình Web" in instructor_page
    assert "Cơ sở dữ liệu" not in instructor_page

    client.post("/logout", data={"csrf_token": csrf_from(client, "/account")})
    login_form(client, "admin@lms.test")
    admin_page = client.get("/account").get_data(as_text=True)
    assert "Lập trình Web" in admin_page
    assert "Cơ sở dữ liệu" in admin_page


def test_logout_clears_session(client):
    login_form(client, "chi.sv@lms.test")
    token = csrf_from(client, "/account")
    response = client.post("/logout", data={"csrf_token": token})
    assert response.status_code == 302
    assert client.get("/account").status_code == 302


def test_forgot_password_sends_mail_only_for_existing_account(client, monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(
        emailer,
        "send_password_reset_email",
        lambda config, recipient, url: sent.append(recipient),
    )

    known = client.post(
        "/forgot-password",
        data={
            "csrf_token": csrf_from(client, "/forgot-password"),
            "email": "chi.sv@lms.test",
        },
    )
    assert known.status_code == 302
    assert sent == ["chi.sv@lms.test"]

    unknown = client.post(
        "/forgot-password",
        data={
            "csrf_token": csrf_from(client, "/forgot-password"),
            "email": "nobody@lms.test",
        },
    )
    assert unknown.status_code == 302
    assert sent == ["chi.sv@lms.test"]


def test_reset_password_page_hides_form_for_invalid_token(client):
    page = client.get("/reset-password?token=khong-hop-le")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "không hợp lệ" in html
    assert 'name="password"' not in html
