"""Bản Before — chưa có optimistic locking: người lưu sau ghi đè người lưu trước."""

import os

import pytest

from app import create_app

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"
GRADES = "/courses/c1/grades"


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


def login(client, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def test_second_save_overwrites_first_silently(client):
    an = login(client, "an.gv@lms.test")

    # Hai tab cùng đọc bảng điểm và thấy u4 = 7.5
    before = client.get(GRADES, headers=auth(an)).get_json()
    assert {"studentId": "u4", "score": 7.5} in before

    # Tab 1 lưu 8.0
    first = client.put("/courses/c1/grades/u4", json={"score": 8}, headers=auth(an))
    assert first.status_code == 200

    # Tab 2 vẫn giữ dữ liệu cũ và lưu 9.0: không có cảnh báo xung đột nào
    second = client.put("/courses/c1/grades/u4", json={"score": 9}, headers=auth(an))
    assert second.status_code == 200
    assert second.get_json() == {"courseId": "c1", "studentId": "u4", "score": 9}

    # Thay đổi của tab 1 biến mất mà không ai biết
    after = client.get(GRADES, headers=auth(an)).get_json()
    assert {"studentId": "u4", "score": 9} in after
    assert {"studentId": "u4", "score": 8} not in after


def test_versioned_grade_endpoint_does_not_exist(client):
    an = login(client, "an.gv@lms.test")
    assert client.get("/courses/c1/grades/u4/v2", headers=auth(an)).status_code == 404
    stale = client.put(
        "/courses/c1/grades/u4/v2",
        json={"score": 5, "expectedVersion": 0},
        headers=auth(an),
    )
    assert stale.status_code == 404
