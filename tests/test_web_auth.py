import re
from urllib.parse import parse_qs, urlparse

import pytest

from app import create_app, emailer
from app import oauth as oauth_module


SECRET = "unit-test-secret-with-at-least-32-characters"


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "DATABASE_PATH": str(tmp_path / "lms.sqlite3"),
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "PUBLIC_BASE_URL": "http://localhost:5000",
            "GOOGLE_CLIENT_ID": "google-client-id",
            "GOOGLE_CLIENT_SECRET": "google-client-secret",
            "GITHUB_CLIENT_ID": "github-client-id",
            "GITHUB_CLIENT_SECRET": "github-client-secret",
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(response):
    match = re.search(
        r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)
    )
    assert match is not None
    return match.group(1)


def test_home_register_and_account_pages_are_connected_to_sqlite(client, app):
    assert client.get("/").status_code == 200
    form = client.get("/register")
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(form),
            "name": "Nguyen Van A",
            "email": "new.student@example.com",
            "password": "SecurePass123",
            "confirm_password": "SecurePass123",
            "terms": "on",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login?registered=1")
    assert client.get("/account").status_code == 302

    stored = app.extensions["lms_store"]["by_email"]["new.student@example.com"]
    assert stored["role"] == "STUDENT"
    assert stored["pw_hash"] != b"SecurePass123"
    persisted = app.extensions["lms_store"]["connection"].execute(
        "SELECT email, name, role FROM users WHERE email = ?",
        ("new.student@example.com",),
    ).fetchone()
    assert persisted == ("new.student@example.com", "Nguyen Van A", "STUDENT")


def test_registration_and_password_reset_api_flow(client, monkeypatch):
    register_page = client.get("/register")
    csrf_token = csrf(register_page)
    registered = client.post(
        "/auth/register",
        json={
            "email": "api.student@example.com",
            "name": "API Student",
            "password": "SecurePass123",
            "termsAccepted": True,
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert registered.status_code == 201
    assert registered.get_json()["user"]["email"] == "api.student@example.com"
    assert "accessToken" not in registered.get_json()

    sent = {}

    def capture_email(config, recipient, reset_url):
        assert isinstance(config, dict)
        sent.update(recipient=recipient, url=reset_url)

    monkeypatch.setattr(emailer, "send_password_reset_email", capture_email)
    requested = client.post(
        "/auth/forgot-password",
        json={"email": "api.student@example.com"},
        headers={"X-CSRF-Token": csrf_token, "Host": "attacker.example"},
    )
    assert requested.status_code == 202
    assert sent["recipient"] == "api.student@example.com"
    assert urlparse(sent["url"]).netloc == "localhost:5000"
    parsed_url = urlparse(sent["url"])
    assert parsed_url.path == "/reset-password"
    reset_token = parse_qs(parsed_url.query)["token"][0]

    reset = client.post(
        "/auth/reset-password",
        json={"token": reset_token, "password": "NewSecurePass456"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert reset.status_code == 200
    assert client.post(
        "/auth/password-reset/confirm",
        json={"token": reset_token, "password": "AnotherPass789"},
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 400
    assert client.post(
        "/auth/login",
        json={
            "email": "api.student@example.com",
            "password": "NewSecurePass456",
        },
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 200
    assert client.post(
        "/auth/login",
        json={"email": "api.student@example.com", "password": "SecurePass123"},
        headers={"X-CSRF-Token": csrf_token},
    ).status_code == 401


def test_registered_account_persists_after_app_restart(tmp_path):
    database = str(tmp_path / "persistent.sqlite3")
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "DATABASE_PATH": database,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    }
    first = create_app(config)
    restarted = create_app(config)
    state = first.extensions["lms_store"]
    from app import auth

    auth.register(
        "persisted@example.com",
        "Persisted Student",
        "SecurePass123",
        SECRET,
        900,
        state,
    )

    response = restarted.test_client().post(
        "/auth/login",
        json={
            "email": "persisted@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 200
    assert (
        restarted.extensions["lms_store"]["by_email"]["persisted@example.com"]["name"]
        == "Persisted Student"
    )


def test_web_forms_require_csrf_and_account_requires_login(client):
    response = client.post(
        "/register",
        data={
            "name": "No CSRF",
            "email": "no-csrf@example.com",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 400
    assert client.get("/account").status_code == 302


def test_auth_pages_render_and_login_sets_httponly_session_cookie(client):
    for path in (
        "/login",
        "/register",
        "/forgot-password",
        "/reset-password",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert "MiniLMS" in response.get_data(as_text=True)

    login_page = client.get("/login")
    token = csrf(login_page)
    response = client.post(
        "/auth/login",
        json={
            "email": "chi.sv@lms.test",
            "password": "Lms@2026",
            "remember": True,
        },
        headers={"X-CSRF-Token": token},
    )
    assert response.status_code == 200
    assert "accessToken" not in response.get_json()
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "Expires=" in cookie
    assert client.get("/account").status_code == 200


def test_browser_api_requires_csrf_header(client):
    page = client.get("/register")
    response = client.post(
        "/auth/register",
        json={
            "email": "csrf@example.com",
            "name": "CSRF User",
            "password": "SecurePass123",
        },
    )
    assert response.status_code == 400

    response = client.post(
        "/auth/register",
        json={
            "email": "csrf@example.com",
            "name": "CSRF User",
            "password": "SecurePass123",
        },
        headers={"X-CSRF-Token": csrf(page)},
    )
    assert response.status_code == 201


def test_registration_requires_strong_password(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "weak@example.com",
            "name": "Weak Password",
            "password": "password1",
        },
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}

    response = client.post(
        "/auth/register",
        json={
            "email": "terms@example.com",
            "name": "Terms User",
            "password": "SecurePass123",
            "termsAccepted": False,
        },
    )
    assert response.status_code == 400


@pytest.mark.parametrize("provider", ["google", "github"])
def test_oauth_login_creates_and_reuses_verified_provider_identity(
    client, app, monkeypatch, provider
):
    provider_urls = {
        "google": "https://oauth2.googleapis.com/token",
        "github": "https://github.com/login/oauth/access_token",
    }
    calls = []

    def fake_request_json(url, **kwargs):
        calls.append((url, kwargs))
        if url == provider_urls[provider]:
            return {"access_token": "provider-access-token"}
        if provider == "google":
            assert url == "https://openidconnect.googleapis.com/v1/userinfo"
            return {
                "sub": "google-user-42",
                "email": "oauth.student@example.com",
                "email_verified": True,
                "name": "OAuth Student",
            }
        if url == "https://api.github.com/user":
            return {"id": 8042, "login": "oauthstudent", "name": "OAuth Student"}
        assert url == "https://api.github.com/user/emails"
        return [
            {
                "email": "oauth.student@example.com",
                "primary": True,
                "verified": True,
            }
        ]

    monkeypatch.setattr(oauth_module, "_request_json", fake_request_json)

    def complete_login():
        started = client.get(f"/oauth/{provider}")
        assert started.status_code == 302
        authorization = urlparse(started.headers["Location"])
        query = parse_qs(authorization.query)
        assert query["code_challenge_method"] == ["S256"]
        assert query["redirect_uri"] == [
            f"http://localhost:5000/oauth/{provider}/callback"
        ]
        callback = client.get(
            f"/oauth/{provider}/callback?code=provider-code&state={query['state'][0]}"
        )
        assert callback.status_code == 302
        assert callback.headers["Location"] == "/"
    complete_login()
    state = app.extensions["lms_store"]
    oauth_rows = state["connection"].execute(
        "SELECT provider, subject FROM oauth_accounts"
    ).fetchall()
    assert oauth_rows == [
        (provider, "google-user-42" if provider == "google" else "8042")
    ]
    account = client.get("/account")
    assert account.status_code == 200
    assert "oauth.student@example.com" in account.get_data(as_text=True)

    with client.session_transaction() as session:
        session.clear()
    complete_login()
    assert state["connection"].execute("SELECT COUNT(*) FROM users").fetchone()[0] == 7
    assert len(calls) == (4 if provider == "google" else 6)
    assert all(
        kwargs.get("headers", {}).get("Authorization")
        == "Bearer provider-access-token"
        for url, kwargs in calls
        if url != provider_urls[provider]
    )


def test_oauth_callback_rejects_state_mismatch_without_provider_request(
    client, monkeypatch
):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("OAuth provider must not be called for invalid state")

    monkeypatch.setattr(oauth_module, "_request_json", fail_if_called)
    client.get("/oauth/google")
    response = client.get("/oauth/google/callback?code=code&state=wrong")
    assert response.status_code == 302
    assert response.headers["Location"] == "/login"
    assert not called


def test_oauth_does_not_automatically_link_an_existing_email(client, app, monkeypatch):
    def fake_request_json(url, **kwargs):
        if url == oauth_module.PROVIDERS["google"]["token_url"]:
            return {"access_token": "provider-access-token"}
        return {
            "sub": "existing-account-owner",
            "email": "chi.sv@lms.test",
            "email_verified": True,
            "name": "Existing Account",
        }

    monkeypatch.setattr(oauth_module, "_request_json", fake_request_json)
    start = client.get("/oauth/google")
    state = parse_qs(urlparse(start.headers["Location"]).query)["state"][0]
    callback = client.get(f"/oauth/google/callback?code=code&state={state}")
    assert callback.headers["Location"] == "/login"
    assert app.extensions["lms_store"]["connection"].execute(
        "SELECT COUNT(*) FROM oauth_accounts"
    ).fetchone()[0] == 0
    login_page = client.get("/login")
    assert "Hãy đăng nhập bằng email và mật khẩu hiện tại." in login_page.get_data(
        as_text=True
    )
