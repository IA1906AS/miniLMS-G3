"""Bước 3.1 — phiên (logout, đổi mật khẩu) và hồ sơ cá nhân."""

import time

import pytest

from app import auth, create_app
from app.account_service import change_password as service_change_password
from app.errors import InvalidCredentials, Unauthenticated
from app.runtime import using_store

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


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client, email: str = "chi.sv@lms.test", password: str = PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def profile(client, token: str):
    return client.get("/users/me", headers=auth_header(token))


def update(client, token: str, body):
    return client.put("/users/me", json=body, headers=auth_header(token))


def change_password(client, token: str, body):
    return client.post("/me/password", json=body, headers=auth_header(token))


# --- Mốc vô hiệu token tính theo giây ------------------------------------


def test_token_from_same_second_survives_invalidation(app):
    now = time.time()
    token = auth.issue_token("u4", SECRET, 900, now=now)
    state = app.extensions["lms_store"]

    state["tokens_valid_after"]["u4"] = int(now)
    assert auth.verify_token(token, SECRET, state)["id"] == "u4"

    state["tokens_valid_after"]["u4"] = int(now) + 1
    with pytest.raises(Unauthenticated):
        auth.verify_token(token, SECRET, state)


# --- POST /auth/logout ----------------------------------------------------


def test_logout_requires_authentication(client):
    assert client.post("/auth/logout").status_code == 401


def test_logout_invalidates_earlier_token(client):
    token = login(client)
    time.sleep(1.05)
    assert client.post("/auth/logout", headers=auth_header(token)).status_code == 200
    assert client.get("/me", headers=auth_header(token)).status_code == 401
    assert client.get("/me", headers=auth_header(login(client))).status_code == 200


# --- POST /me/password ----------------------------------------------------


def test_password_change_success_and_relogin(client):
    token = login(client)

    response = change_password(
        client, token, {"oldPassword": PASSWORD, "newPassword": "MatKhauMoi123"}
    )
    assert response.status_code == 200
    assert response.get_json() == {"message": "Password updated"}

    assert (
        client.post(
            "/auth/login", json={"email": "chi.sv@lms.test", "password": PASSWORD}
        ).status_code
        == 401
    )
    assert login(client, "chi.sv@lms.test", "MatKhauMoi123")


def test_password_change_invalidates_earlier_token(client):
    token = login(client)
    time.sleep(1.05)
    change_password(client, token, {"oldPassword": PASSWORD, "newPassword": "MatKhauMoi123"})
    assert client.get("/me", headers=auth_header(token)).status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {"oldPassword": PASSWORD, "newPassword": "short1"},  # < 10
        {"oldPassword": PASSWORD, "newPassword": "khongcoso"},  # không có số
        {"oldPassword": PASSWORD, "newPassword": "1234567890"},  # không có chữ
        {"oldPassword": PASSWORD, "newPassword": PASSWORD},  # trùng mật khẩu cũ
        {"oldPassword": PASSWORD, "newPassword": "MatKhauMoi123", "extra": 1},
        {"oldPassword": PASSWORD},
        {"oldPassword": 123, "newPassword": "MatKhauMoi123"},
    ],
)
def test_password_change_rejects_invalid_bodies(client, body):
    response = change_password(client, login(client), body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_password_change_rejects_wrong_old_password(client):
    response = change_password(
        client, login(client), {"oldPassword": "SaiMatKhau123", "newPassword": "MatKhauMoi123"}
    )
    assert response.status_code == 401
    assert response.get_json() == {"error": "INVALID_CREDENTIALS"}


def test_password_change_service_rechecks_old_password(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with using_store(app.extensions["lms_store"]), pytest.raises(InvalidCredentials):
        service_change_password(chi, "khong-dung", "MatKhauMoi123")


# --- GET/PUT /users/me ----------------------------------------------------


def test_profile_contract_has_no_secret_fields(client):
    response = profile(client, login(client))
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"id", "email", "fullName", "bio", "role"}
    text = response.get_data(as_text=True).lower()
    assert "pw_hash" not in text and "password" not in text


def test_profile_update_full_name_and_bio(client, app):
    token = login(client)
    response = update(client, token, {"fullName": "Chi Nguyễn", "bio": "Sinh viên CNTT"})
    assert response.status_code == 200
    assert response.get_json()["fullName"] == "Chi Nguyễn"
    assert response.get_json()["bio"] == "Sinh viên CNTT"

    stored = (
        app.extensions["lms_store"]["connection"]
        .execute("SELECT name, bio FROM users WHERE id = 'u4'")
        .fetchone()
    )
    assert stored == ("Chi Nguyễn", "Sinh viên CNTT")

    assert update(client, token, {"bio": "Chỉ đổi bio"}).get_json()["bio"] == "Chỉ đổi bio"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"role": "ADMIN"},
        {"email": "hacker@lms.test"},
        {"id": "u1"},
        {"fullName": "A", "role": "ADMIN"},
        {"fullName": 123},
        {"bio": None},
        {"fullName": "x" * 101},
        {"bio": "x" * 501},
    ],
)
def test_profile_update_rejects_mass_assignment(client, body):
    response = update(client, login(client), body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_profile_requires_authentication(client):
    assert client.get("/users/me").status_code == 401
    assert client.put("/users/me", json={"fullName": "X"}).status_code == 401


# --- Audit ----------------------------------------------------------------


def test_account_writes_are_audited_once_each(app, client):
    token = login(client)
    change_password(client, token, {"oldPassword": PASSWORD, "newPassword": "MatKhauMoi123"})
    token = login(client, "chi.sv@lms.test", "MatKhauMoi123")
    update(client, token, {"bio": "Xin chào"})

    with open(app.extensions["lms_store"]["audit_log_path"], encoding="utf-8") as audit_file:
        entries = [line for line in audit_file.read().splitlines() if line.strip()]
    assert len(entries) == 2
    assert "PASSWORD_CHANGE" in entries[0]
    assert "PROFILE_UPDATE" in entries[1]
    assert "MatKhauMoi123" not in "\n".join(entries)
