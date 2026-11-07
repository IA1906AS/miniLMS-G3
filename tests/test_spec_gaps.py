"""Bổ sung theo đặc tả: quiz, diễn đàn, audit đăng nhập, GV tạo khoá học."""

import json
import os

import pytest

from app import create_app

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


def login(client, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def make_quiz(duration: int = 10, max_attempts: int = 3) -> dict:
    return {
        "title": "Quiz đặc tả",
        "description": "",
        "durationMinutes": duration,
        "maxAttempts": max_attempts,
        "questions": [
            {"question": "2+2?", "options": ["3", "4"], "correctOption": 1, "points": 1.0}
        ],
    }


def create_quiz(client, token, duration=10, max_attempts=3):
    response = client.post(
        "/courses/c1/quizzes",
        json=make_quiz(duration, max_attempts),
        headers=auth(token),
    )
    assert response.status_code == 201
    return response.get_json()["id"]


# --- 1. Giới hạn thời lượng làm bài -----------------------------------------


def test_submit_within_duration_succeeds(app, client):
    an = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    quiz_id = create_quiz(client, an, duration=10)

    attempt = client.post(f"/quizzes/{quiz_id}/attempts", headers=auth(chi))
    attempt_id = attempt.get_json()["id"]
    submitted = client.post(
        f"/quizzes/{quiz_id}/attempts/{attempt_id}/submit", json={"answers": {}}, headers=auth(chi)
    )
    assert submitted.status_code == 200


def test_submit_after_duration_is_rejected(app, client):
    an = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    quiz_id = create_quiz(client, an, duration=1)

    attempt = client.post(f"/quizzes/{quiz_id}/attempts", headers=auth(chi))
    attempt_id = attempt.get_json()["id"]

    state = app.extensions["lms_store"]
    base = state["now"]()
    state["now"] = lambda: base + 120  # quá 1 phút

    late = client.post(
        f"/quizzes/{quiz_id}/attempts/{attempt_id}/submit", json={"answers": {}}, headers=auth(chi)
    )
    assert late.status_code == 409
    assert late.get_json() == {"error": "TIME_EXPIRED"}


# --- 2. Diễn đàn: sửa và xoá nội dung của chính mình -------------------------


def test_owner_can_edit_own_thread_but_others_cannot(client):
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")
    an = login(client, "an.gv@lms.test")

    created = client.post(
        "/courses/c1/threads",
        json={"title": "Chủ đề", "body": "Nội dung gốc"},
        headers=auth(chi),
    )
    assert created.status_code == 201
    thread_id = created.get_json()["id"]

    updated = client.patch(
        f"/threads/{thread_id}",
        json={"title": "Chủ đề mới", "body": "Nội dung đã sửa"},
        headers=auth(chi),
    )
    assert updated.status_code == 200
    assert updated.get_json()["title"] == "Chủ đề mới"
    assert updated.get_json()["body"] == "Nội dung đã sửa"

    other = client.patch(
        f"/threads/{thread_id}",
        json={"title": "X", "body": "Y"},
        headers=auth(dung),
    )
    assert other.status_code == 403

    teacher = client.patch(
        f"/threads/{thread_id}",
        json={"title": "GV sửa", "body": "Nội dung GV"},
        headers=auth(an),
    )
    assert teacher.status_code == 200


def test_owner_can_delete_own_thread_but_others_cannot(client):
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")

    thread_id = client.post(
        "/courses/c1/threads",
        json={"title": "Chủ đề", "body": "Nội dung"},
        headers=auth(chi),
    ).get_json()["id"]

    assert client.delete(f"/threads/{thread_id}", headers=auth(dung)).status_code == 403
    assert client.delete(f"/threads/{thread_id}", headers=auth(chi)).status_code == 200


def test_owner_can_edit_and_delete_own_comment(client):
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")

    thread_id = client.post(
        "/courses/c1/threads",
        json={"title": "Chủ đề", "body": "Nội dung"},
        headers=auth(chi),
    ).get_json()["id"]
    comment_id = client.post(
        f"/threads/{thread_id}/comments", json={"body": "Bình luận"}, headers=auth(chi)
    ).get_json()["id"]

    assert (
        client.patch(
            f"/comments/{comment_id}", json={"body": "Khác"}, headers=auth(dung)
        ).status_code
        == 403
    )
    edited = client.patch(f"/comments/{comment_id}", json={"body": "Đã sửa"}, headers=auth(chi))
    assert edited.status_code == 200
    assert edited.get_json()["body"] == "Đã sửa"
    assert client.delete(f"/comments/{comment_id}", headers=auth(chi)).status_code == 200


# --- 3. Audit sự kiện đăng nhập ---------------------------------------------


def test_api_login_is_audited(app, client):
    login(client, "chi.sv@lms.test")
    path = app.extensions["lms_store"]["audit_log_path"]
    with open(path, encoding="utf-8") as handle:
        entries = [json.loads(line) for line in handle if line.strip()]
    logins = [entry for entry in entries if entry["action"] == "LOGIN"]
    assert logins and logins[0]["actorId"] == "u4"
    assert "password" not in json.dumps(logins[0]).lower()


def test_web_login_is_audited(app, client):
    import re

    page = client.get("/login")
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    response = client.post(
        "/login", data={"csrf_token": csrf, "email": "chi.sv@lms.test", "password": PASSWORD}
    )
    assert response.status_code == 302
    path = app.extensions["lms_store"]["audit_log_path"]
    with open(path, encoding="utf-8") as handle:
        entries = [json.loads(line) for line in handle if line.strip()]
    assert any(entry["action"] == "LOGIN" and entry["resource"] == "/login" for entry in entries)


# --- 4. Giảng viên tự tạo khoá học ------------------------------------------


def test_instructor_creates_course_for_themselves(client):
    an = login(client, "an.gv@lms.test")
    created = client.post(
        "/courses",
        json={"name": "Môn của tôi", "instructorId": "u3"},
        headers=auth(an),
    )
    assert created.status_code == 201
    assert created.get_json()["instructorId"] == "u2"  # luôn là chính giảng viên

    listed = client.get("/courses?instructor=u2", headers=auth(an)).get_json()
    assert any(course["name"] == "Môn của tôi" for course in listed)


def test_student_cannot_create_course(client):
    chi = login(client, "chi.sv@lms.test")
    response = client.post(
        "/courses", json={"name": "Môn lạ", "instructorId": "u2"}, headers=auth(chi)
    )
    assert response.status_code == 403
