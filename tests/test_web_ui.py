"""Kiểm thử giao diện web (server-rendered) cho các tính năng trong đặc tả."""

import io
import os
import re

import pytest

from app import create_app
from app import store as store_module

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
            "AVATAR_FOLDER": str(tmp_path / "avatars"),
            "MATERIAL_FOLDER": str(tmp_path / "materials"),
            "SUBMISSION_FOLDER": str(tmp_path / "submissions"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client, path="/login"):
    page = client.get(path)
    return re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)


def login(client, email, password=PASSWORD):
    response = client.post(
        "/login",
        data={
            "csrf_token": csrf(client),
            "email": email,
            "password": password,
        },
    )
    assert response.status_code == 302
    return client


def post(client, path, data, from_path=None):
    payload = dict(data)
    payload.setdefault("csrf_token", csrf(client, from_path or path))
    return client.post(path, data=payload, follow_redirects=False)


def test_courses_page_requires_login(client):
    response = client.get("/ui/courses")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_student_sees_courses_and_course_detail(client):
    login(client, "chi.sv@lms.test")
    listing = client.get("/ui/courses")
    assert listing.status_code == 200
    assert "Lập trình Web" in listing.get_data(as_text=True)
    detail = client.get("/ui/courses/c1")
    assert detail.status_code == 200
    assert "Thành viên" in detail.get_data(as_text=True)


def test_non_enrolled_student_cannot_view_course(client):
    login(client, "em.sv@lms.test")  # chỉ ghi danh c2
    assert client.get("/ui/courses/c1").status_code == 403


def test_profile_update_and_password_change(client, app):
    login(client, "chi.sv@lms.test")
    response = post(
        client,
        "/account/profile",
        {"fullName": "Chi Nguyễn", "bio": "hello", "phone": "0901234567"},
        from_path="/account",
    )
    assert response.status_code == 302
    state = app.extensions["lms_store"]
    store_module.refresh(state)
    assert state["users"]["u4"]["name"] == "Chi Nguyễn"
    assert state["bios"]["u4"] == "hello"
    assert state["phones"]["u4"] == "0901234567"

    wrong = post(
        client,
        "/account/password",
        {
            "oldPassword": "sai-mat-khau",
            "newPassword": "Moi1234567",
            "confirmPassword": "Moi1234567",
        },
        from_path="/account",
    )
    assert wrong.status_code == 302
    ok = post(
        client,
        "/account/password",
        {"oldPassword": PASSWORD, "newPassword": "Moi1234567", "confirmPassword": "Moi1234567"},
        from_path="/account",
    )
    assert ok.status_code == 302
    assert "/login" in ok.headers["Location"]


def test_avatar_upload_and_serve(client):
    login(client, "chi.sv@lms.test")
    token = csrf(client, "/account")
    png = bytes.fromhex("89504e470d0a1a0a") + b"0" * 32
    response = client.post(
        "/account/avatar",
        data={"csrf_token": token, "avatar": (io.BytesIO(png), "me.png")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302
    served = client.get("/ui/avatar/u4")
    assert served.status_code == 200


def test_instructor_creates_course_via_web(client, app):
    login(client, "an.gv@lms.test")
    response = post(client, "/ui/courses", {"name": "Môn mới"}, from_path="/ui/courses")
    assert response.status_code == 302
    state = app.extensions["lms_store"]
    store_module.refresh(state)
    created = [course for course in state["courses"].values() if course["name"] == "Môn mới"]
    assert created and created[0]["instructorId"] == "u2"


def test_student_cannot_create_course_via_web(client):
    login(client, "chi.sv@lms.test")
    response = post(client, "/ui/courses", {"name": "X"}, from_path="/ui/courses")
    assert response.status_code == 403


def test_material_upload_download_and_access_control(client, app):
    login(client, "an.gv@lms.test")
    token = csrf(client, "/ui/courses/c1")
    response = client.post(
        "/ui/courses/c1/materials",
        data={
            "csrf_token": token,
            "title": "Slide",
            "file": (io.BytesIO(b"%PDF-1.4 test"), "slide.pdf"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    html = client.get("/ui/courses/c1").get_data(as_text=True)
    material_url = re.search(r"/materials/([A-Za-z0-9_]+)/download", html).group(1)
    assert client.get(f"/ui/materials/{material_url}/download").status_code == 200

    other = app.test_client()
    login(other, "em.sv@lms.test")
    assert other.get(f"/ui/materials/{material_url}/download").status_code == 403


def test_assignment_submit_and_grade(client, app):
    login(client, "an.gv@lms.test")
    post(
        client,
        "/ui/courses/c1/assignments",
        {"title": "BT web", "description": "nộp", "dueAt": "2027-01-01T17:00"},
        from_path="/ui/courses/c1",
    )
    html = client.get("/ui/courses/c1").get_data(as_text=True)
    assignment_id = re.search(r"/assignments/([A-Za-z0-9_]+)", html).group(1)

    student = app.test_client()
    login(student, "chi.sv@lms.test")
    assert student.get(f"/ui/assignments/{assignment_id}").status_code == 200
    response = post(
        student,
        f"/ui/assignments/{assignment_id}/submit",
        {"content": "bài làm"},
        from_path=f"/ui/assignments/{assignment_id}",
    )
    assert response.status_code == 302
    assert "bài làm" in student.get(f"/ui/assignments/{assignment_id}").get_data(as_text=True)

    page = client.get(f"/ui/assignments/{assignment_id}").get_data(as_text=True)
    submission_id = re.search(r"/submissions/([A-Za-z0-9_]+)/grade", page).group(1)
    graded = post(
        client,
        f"/ui/submissions/{submission_id}/grade",
        {"grade": "9", "feedback": "tốt"},
        from_path=f"/ui/assignments/{assignment_id}",
    )
    assert graded.status_code == 302
    assert "9.0" in student.get(f"/ui/assignments/{assignment_id}").get_data(as_text=True)


def test_quiz_create_start_and_submit(client, app):
    login(client, "an.gv@lms.test")
    post(
        client,
        "/ui/courses/c1/quizzes",
        {
            "title": "Quiz web",
            "description": "",
            "durationMinutes": "10",
            "maxAttempts": "2",
            "questions": "2+2? | 3 | 4 | 1",
        },
        from_path="/ui/courses/c1",
    )
    html = client.get("/ui/courses/c1").get_data(as_text=True)
    quiz_id = re.search(r"/quizzes/([A-Za-z0-9_]+)", html).group(1)

    student = app.test_client()
    login(student, "chi.sv@lms.test")
    started = post(
        student, f"/ui/quizzes/{quiz_id}/attempts", {}, from_path=f"/ui/quizzes/{quiz_id}"
    )
    assert started.status_code == 302
    attempt_url = started.headers["Location"]
    attempt_page = student.get(attempt_url)
    assert attempt_page.status_code == 200
    question_id = re.search(r'name="q_([A-Za-z0-9_]+)"', attempt_page.get_data(as_text=True)).group(
        1
    )
    token = re.search(
        r'name="csrf_token" value="([^"]+)"', attempt_page.get_data(as_text=True)
    ).group(1)
    submitted = student.post(
        f"{attempt_url}/submit",
        data={"csrf_token": token, f"q_{question_id}": "1"},
        follow_redirects=False,
    )
    assert submitted.status_code == 302
    detail = student.get(f"/ui/quizzes/{quiz_id}").get_data(as_text=True)
    assert "10.0" in detail


def test_forum_create_edit_delete_owner(client):
    login(client, "chi.sv@lms.test")
    created = post(
        client,
        "/ui/courses/c1/threads",
        {"title": "Chủ đề", "body": "Nội dung"},
        from_path="/ui/courses/c1",
    )
    assert created.status_code == 302
    thread_url = created.headers["Location"]

    updated = post(
        client,
        f"{thread_url}/update",
        {"title": "Đã sửa", "body": "Nội dung mới"},
        from_path=thread_url,
    )
    assert updated.status_code == 302
    assert "Đã sửa" in client.get(thread_url).get_data(as_text=True)

    other = client.application.test_client()
    login(other, "dung.sv@lms.test")
    assert other.get(thread_url).status_code == 200
    assert (
        other.post(
            f"{thread_url}/update",
            data={"csrf_token": csrf(other, thread_url), "title": "x", "body": "y"},
            follow_redirects=False,
        ).status_code
        == 403
    )


def test_admin_panel_requires_admin_and_can_lock_user(client, app):
    login(client, "chi.sv@lms.test")
    assert client.get("/ui/admin").status_code == 403

    admin = app.test_client()
    login(admin, "admin@lms.test")
    assert admin.get("/ui/admin").status_code == 200
    token = csrf(admin, "/ui/admin")
    assert admin.post("/ui/admin/users/u6/lock", data={"csrf_token": token}).status_code == 302
    state = app.extensions["lms_store"]
    assert state["locked"]["u6"] is True
    assert admin.post("/ui/admin/users/u6/unlock", data={"csrf_token": token}).status_code == 302
    assert state["locked"]["u6"] is False
