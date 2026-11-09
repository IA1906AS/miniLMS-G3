"""Phase 1 — bài học, xuất bản khoá học, quản trị tài khoản và học viên."""

import os
import re

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


def login(client, email: str, password: str = PASSWORD) -> str:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def get(client, token, path):
    return client.get(path, headers=auth(token))


def post(client, token, path, payload):
    return client.post(path, json=payload, headers=auth(token))


def web_login(client, email: str, password: str = PASSWORD):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password},
        follow_redirects=True,
    )
    page = client.get("/ui/courses")
    match = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True))
    return match.group(1) if match else ""


# --- Quản trị tài khoản ---------------------------------------------------


def test_admin_can_create_and_delete_account(client):
    admin = login(client, "admin@lms.test")
    payload = {
        "email": "moi@lms.test",
        "name": "Người Mới",
        "password": "Abcdef12345",
        "role": "INSTRUCTOR",
    }
    created = post(client, admin, "/admin/users", payload)
    assert created.status_code == 201
    user_id = created.get_json()["id"]
    assert created.get_json()["role"] == "INSTRUCTOR"

    duplicate = post(client, admin, "/admin/users", payload)
    assert duplicate.status_code == 409

    assert client.delete(f"/admin/users/{user_id}", headers=auth(admin)).status_code == 200
    assert client.delete(f"/admin/users/{user_id}", headers=auth(admin)).status_code == 404


def test_admin_cannot_delete_self_last_admin_or_course_owner(client):
    admin = login(client, "admin@lms.test")
    me = get(client, admin, "/users/me").get_json()["id"]
    assert client.delete(f"/admin/users/{me}", headers=auth(admin)).status_code == 400

    # an.gv đang phụ trách c1 nên không xoá được
    instructor = get(client, login(client, "an.gv@lms.test"), "/users/me").get_json()["id"]
    assert client.delete(f"/admin/users/{instructor}", headers=auth(admin)).status_code == 409


def test_only_admin_can_create_account(client):
    instructor = login(client, "an.gv@lms.test")
    response = post(
        client,
        instructor,
        "/admin/users",
        {"email": "x@lms.test", "name": "X", "password": "Abcdef12345", "role": "STUDENT"},
    )
    assert response.status_code == 403


# --- Xuất bản khoá học ----------------------------------------------------


def test_instructor_publishes_and_hides_course(client):
    instructor = login(client, "an.gv@lms.test")
    student = login(client, "em.sv@lms.test")
    assert "c1" in [c["id"] for c in get(client, student, "/courses").get_json()]

    hidden = client.patch(
        "/courses/c1/publish", json={"published": False}, headers=auth(instructor)
    )
    assert hidden.status_code == 200
    assert hidden.get_json()["published"] is False
    assert "c1" not in [c["id"] for c in get(client, student, "/courses").get_json()]

    shown = client.patch("/courses/c1/publish", json={"published": True}, headers=auth(instructor))
    assert shown.status_code == 200
    assert "c1" in [c["id"] for c in get(client, student, "/courses").get_json()]


def test_other_instructor_cannot_publish_course(client):
    other = login(client, "binh.gv@lms.test")
    response = client.patch("/courses/c1/publish", json={"published": False}, headers=auth(other))
    assert response.status_code == 403


def test_instructor_can_delete_own_course_but_not_others(client):
    instructor = login(client, "an.gv@lms.test")
    instructor_id = get(client, instructor, "/users/me").get_json()["id"]
    created = post(
        client, instructor, "/courses", {"name": "Khoá tạm", "instructorId": instructor_id}
    )
    assert created.status_code == 201
    course_id = created.get_json()["id"]
    assert client.delete(f"/courses/{course_id}", headers=auth(instructor)).status_code == 200

    other = login(client, "binh.gv@lms.test")
    assert client.delete("/courses/c1", headers=auth(other)).status_code == 403


# --- Bài học -------------------------------------------------------------


def test_lesson_crud_and_student_progress(client):
    instructor = login(client, "an.gv@lms.test")
    student = login(client, "chi.sv@lms.test")
    outsider = login(client, "em.sv@lms.test")

    created = post(
        client,
        instructor,
        "/courses/c1/lessons",
        {"title": "Bài 1", "body": "Nội dung", "videoUrl": "", "isPreview": False},
    )
    assert created.status_code == 201
    lesson_id = created.get_json()["id"]

    listed = get(client, student, "/courses/c1/lessons").get_json()
    assert [lesson["id"] for lesson in listed] == [lesson_id]
    assert get(client, outsider, "/courses/c1/lessons").status_code == 403

    assert post(client, student, f"/lessons/{lesson_id}/complete", {}).status_code == 200
    progress = get(client, student, "/courses/c1/progress").get_json()
    assert progress["completedLessons"] == 1 and progress["percent"] == 100.0

    assert post(client, student, "/courses/c1/lessons", {"title": "X"}).status_code == 403

    updated = client.patch(
        f"/lessons/{lesson_id}",
        json={"title": "Bài 1 sửa", "body": "Mới", "videoUrl": "", "isPreview": True},
        headers=auth(instructor),
    )
    assert updated.status_code == 200
    assert updated.get_json()["isPreview"] is True

    assert client.delete(f"/lessons/{lesson_id}", headers=auth(instructor)).status_code == 200
    assert get(client, student, f"/lessons/{lesson_id}").status_code == 404


def test_lesson_validation(client):
    instructor = login(client, "an.gv@lms.test")
    assert post(client, instructor, "/courses/c1/lessons", {"title": "  "}).status_code == 400
    assert (
        post(
            client,
            instructor,
            "/courses/c1/lessons",
            {"title": "A", "body": "B", "extra": 1},
        ).status_code
        == 400
    )


# --- Giao diện (mỗi endpoint có nút bấm) -----------------------------------


def test_web_course_page_has_lesson_and_student_buttons(client):
    web_login(client, "an.gv@lms.test")
    page = client.get("/ui/courses/c1").get_data(as_text=True)
    assert "Thêm bài học" in page
    assert "Xuất bản khoá học" in page or "Ẩn khoá học" in page
    assert "Thêm sinh viên" in page or "Chưa có sinh viên" in page


def test_web_lesson_page_renders_and_complete_form(client):
    instructor = login(client, "an.gv@lms.test")
    created = post(
        client, instructor, "/courses/c1/lessons", {"title": "Trang bài học", "body": "abc"}
    )
    lesson_id = created.get_json()["id"]

    web_login(client, "chi.sv@lms.test")
    page = client.get(f"/ui/lessons/{lesson_id}").get_data(as_text=True)
    assert "Trang bài học" in page
    assert "Đánh dấu hoàn thành" in page


def test_web_admin_create_account_form(client):
    web_login(client, "admin@lms.test")
    page = client.get("/ui/admin").get_data(as_text=True)
    assert "Tạo tài khoản" in page
    assert 'name="role"' in page
