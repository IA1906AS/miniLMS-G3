"""Bước 3.3 — quản trị người dùng, khoá tài khoản và audit."""

import os
import time

import pytest

from app import admin_service, create_app
from app.errors import Forbidden
from app.runtime import using_store

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
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


def get(client, token, path):
    return client.get(path, headers=auth(token))


def post(client, token, path, body=None):
    return client.post(path, json=body, headers=auth(token))


def patch(client, token, path, body):
    return client.patch(path, json=body, headers=auth(token))


# --- GET /admin/users -----------------------------------------------------


def test_admin_users_list_has_lock_state_and_no_hash(client):
    response = get(client, login(client, "admin@lms.test"), "/admin/users")
    assert response.status_code == 200
    users = response.get_json()
    assert len(users) == 6
    assert all(set(user) == {"id", "email", "name", "role", "locked"} for user in users)
    assert all(user["locked"] is False for user in users)
    assert "pw_hash" not in response.get_data(as_text=True).lower()


def test_non_admin_cannot_list_users(client):
    for email in ("an.gv@lms.test", "chi.sv@lms.test"):
        assert get(client, login(client, email), "/admin/users").status_code == 403


# --- Lock / unlock --------------------------------------------------------


def test_admin_locks_and_unlocks_user(client):
    admin = login(client, "admin@lms.test")
    chi = login(client, "chi.sv@lms.test")

    locked = post(client, admin, "/admin/users/u4/lock")
    assert locked.status_code == 200
    assert locked.get_json()["locked"] is True

    assert get(client, chi, "/me").status_code == 401
    assert get(client, chi, "/me").get_json() == {"error": "UNAUTHENTICATED"}

    blocked = client.post("/auth/login", json={"email": "chi.sv@lms.test", "password": PASSWORD})
    assert blocked.status_code == 429
    assert blocked.get_json() == {"error": "ACCOUNT_LOCKED"}

    unlocked = post(client, admin, "/admin/users/u4/unlock")
    assert unlocked.status_code == 200
    assert unlocked.get_json()["locked"] is False
    assert get(client, login(client, "chi.sv@lms.test"), "/me").status_code == 200


def test_lock_state_is_idempotent_conflict(client):
    admin = login(client, "admin@lms.test")
    assert post(client, admin, "/admin/users/u4/lock").status_code == 200
    assert post(client, admin, "/admin/users/u4/lock").status_code == 409
    assert post(client, admin, "/admin/users/u4/unlock").status_code == 200
    assert post(client, admin, "/admin/users/u4/unlock").status_code == 409


def test_cannot_lock_self_or_last_admin(client):
    admin = login(client, "admin@lms.test")
    response = post(client, admin, "/admin/users/u1/lock")
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_lock_unknown_user_is_404(client):
    admin = login(client, "admin@lms.test")
    assert post(client, admin, "/admin/users/u99/lock").status_code == 404
    assert post(client, admin, "/admin/users/u99/unlock").status_code == 404


def test_only_admin_can_lock(client):
    for email in ("an.gv@lms.test", "chi.sv@lms.test"):
        token = login(client, email)
        assert post(client, token, "/admin/users/u4/lock").status_code == 403
        assert post(client, token, "/admin/users/u4/unlock").status_code == 403


def test_locked_user_stays_in_store_and_keeps_grades(client, app):
    admin = login(client, "admin@lms.test")
    post(client, admin, "/admin/users/u4/lock")
    stored = app.extensions["lms_store"]["users"]["u4"]
    assert stored["role"] == "STUDENT"
    assert app.extensions["lms_store"]["enrollments"][("c1", "u4")] == 7.5


# --- Role change (đã có từ trước, kiểm tra lại sau khi tách file) ---------


def test_role_change_and_token_invalidation(client):
    chi = login(client, "chi.sv@lms.test")
    admin = login(client, "admin@lms.test")
    time.sleep(1.05)  # mốc vô hiệu tính theo giây

    response = patch(client, admin, "/admin/users/u4/role", {"role": "INSTRUCTOR"})
    assert response.status_code == 200
    assert response.get_json()["role"] == "INSTRUCTOR"
    assert get(client, chi, "/me").status_code == 401


# --- GET /admin/audit -----------------------------------------------------


def test_admin_reads_audit_entries(client, app):
    admin = login(client, "admin@lms.test")
    post(client, admin, "/admin/users/u4/lock")
    post(client, admin, "/admin/users/u4/unlock")

    response = get(client, admin, "/admin/audit")
    assert response.status_code == 200
    entries = [entry for entry in response.get_json() if entry["action"] != "LOGIN"]
    assert len(entries) == 2
    assert [entry["action"] for entry in entries] == ["USER_LOCK", "USER_UNLOCK"]
    assert set(entries[0]) >= {"ts", "actorId", "action", "resource", "result"}
    text = response.get_data(as_text=True).lower()
    assert PASSWORD.lower() not in text


def test_audit_limit_is_validated(client):
    admin = login(client, "admin@lms.test")
    post(client, admin, "/admin/users/u4/lock")
    assert len(get(client, admin, "/admin/audit?limit=1").get_json()) == 1
    for raw in ("0", "1001", "abc", "-1"):
        response = get(client, admin, f"/admin/audit?limit={raw}")
        assert response.status_code == 400
        assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_audit_requires_admin(client):
    for email in ("an.gv@lms.test", "chi.sv@lms.test"):
        assert get(client, login(client, email), "/admin/audit").status_code == 403


# --- Lớp 4 ----------------------------------------------------------------


def test_admin_services_recheck_authorization(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with using_store(app.extensions["lms_store"]):
        with pytest.raises(Forbidden):
            admin_service.set_locked(chi, "u5", True)
        with pytest.raises(Forbidden):
            admin_service.list_users(chi)
        with pytest.raises(Forbidden):
            admin_service.read_audit(chi, 10)
