"""Bước 3.6 — optimistic locking cho điểm, không đổi hợp đồng endpoint lõi."""

import pytest

from app import create_app, grade_version_service
from app.errors import Conflict, Forbidden
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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def get(client, token, path):
    return client.get(path, headers=auth(token))


def put(client, token, path, body):
    return client.put(path, json=body, headers=auth(token))


V2 = "/courses/c1/grades/u4/v2"


def test_v2_get_returns_initial_version(client):
    an = login(client, "an.gv@lms.test")
    response = get(client, an, V2)
    assert response.status_code == 200
    assert response.get_json() == {
        "courseId": "c1",
        "studentId": "u4",
        "score": 7.5,
        "version": 0,
    }


def test_v2_update_with_matching_version(client):
    an = login(client, "an.gv@lms.test")
    response = put(client, an, V2, {"score": 9, "expectedVersion": 0})
    assert response.status_code == 200
    assert response.get_json() == {
        "courseId": "c1",
        "studentId": "u4",
        "score": 9,
        "version": 1,
    }
    assert get(client, an, V2).get_json()["version"] == 1


def test_v2_stale_version_is_conflict_and_keeps_first_write(client):
    an = login(client, "an.gv@lms.test")
    assert put(client, an, V2, {"score": 9, "expectedVersion": 0}).status_code == 200

    stale = put(client, an, V2, {"score": 4, "expectedVersion": 0})
    assert stale.status_code == 409
    assert stale.get_json() == {"error": "CONFLICT"}
    assert get(client, an, V2).get_json()["score"] == 9


def test_core_put_bumps_version_so_v2_detects_it(client):
    an = login(client, "an.gv@lms.test")
    before = get(client, an, V2).get_json()["version"]

    core = put(client, an, "/courses/c1/grades/u4", {"score": 8})
    assert core.status_code == 200
    after = get(client, an, V2).get_json()["version"]
    assert after == before + 1

    stale = put(client, an, V2, {"score": 3, "expectedVersion": before})
    assert stale.status_code == 409


def test_core_contracts_are_unchanged(client):
    an = login(client, "an.gv@lms.test")
    updated = put(client, an, "/courses/c1/grades/u4", {"score": 8})
    assert updated.get_json() == {"courseId": "c1", "studentId": "u4", "score": 8}

    chi = login(client, "chi.sv@lms.test")
    listed = get(client, chi, "/courses/c1/grades")
    assert listed.get_json() == [{"studentId": "u4", "score": 8}]


def test_v2_permissions(client):
    chi = login(client, "chi.sv@lms.test")
    assert get(client, chi, V2).status_code == 403
    assert put(client, chi, V2, {"score": 5, "expectedVersion": 0}).status_code == 403

    binh = login(client, "binh.gv@lms.test")
    assert get(client, binh, V2).status_code == 403

    an = login(client, "an.gv@lms.test")
    assert get(client, an, "/courses/c9/grades/u4/v2").status_code == 404
    assert get(client, an, "/courses/c1/grades/u6/v2").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"score": 5},
        {"expectedVersion": 0},
        {"score": 5, "expectedVersion": 0, "extra": 1},
        {"score": 11, "expectedVersion": 0},
        {"score": "10", "expectedVersion": 0},
        {"score": 5, "expectedVersion": "0"},
        {"score": 5, "expectedVersion": True},
        {"score": 5, "expectedVersion": -1},
        {"score": float("nan"), "expectedVersion": 0},
    ],
)
def test_v2_body_validation(client, body):
    response = put(client, login(client, "an.gv@lms.test"), V2, body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_v2_write_is_audited_once(client, app):
    an = login(client, "an.gv@lms.test")
    put(client, an, V2, {"score": 9, "expectedVersion": 0})

    with open(app.extensions["lms_store"]["audit_log_path"], encoding="utf-8") as audit_file:
        lines = [line for line in audit_file.read().splitlines() if line.strip()]
    assert len(lines) == 1
    assert "UPDATE_GRADE" in lines[0]
    assert '"version": 1' in lines[0]


def test_v2_service_rechecks_authorization(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with using_store(app.extensions["lms_store"]):
        with pytest.raises(Forbidden):
            grade_version_service.update_grade(chi, "c1", "u4", 5, 0)
        with pytest.raises(Conflict):
            grade_version_service.update_grade(
                {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"},
                "c1",
                "u4",
                5,
                99,
            )
