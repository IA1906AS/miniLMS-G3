"""Kiểm thử Lưu trữ tệp, Tài liệu bài giảng, Ảnh đại diện, và Chấm điểm bài tập."""

import io
import os

import pytest

from app import create_app

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"


@pytest.fixture
def app(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "UPLOAD_FOLDER": str(upload_dir / "materials"),
            "AVATAR_FOLDER": str(upload_dir / "avatars"),
            "SUBMISSION_FOLDER": str(upload_dir / "submissions"),
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


# --- Avatar ---------------------------------------------------------------


def test_avatar_upload_and_retrieve(client):
    an = login(client, "an.gv@lms.test")

    # Upload avatar
    data = {
        "avatar": (io.BytesIO(b"\x89PNG\r\n\x1a\nfake-png-data"), "avatar.png"),
    }
    response = client.post(
        "/users/me/avatar",
        data=data,
        content_type="multipart/form-data",
        headers=auth(an),
    )
    assert response.status_code == 200
    avatar_name = response.get_json()["avatar"]
    assert avatar_name.endswith(".png")

    # Get avatar
    get_res = client.get("/users/u2/avatar", headers=auth(an))
    assert get_res.status_code == 200
    assert get_res.data == b"\x89PNG\r\n\x1a\nfake-png-data"

    # User without avatar -> 404
    assert client.get("/users/u1/avatar", headers=auth(an)).status_code == 404


def test_avatar_upload_rejects_invalid_extension(client):
    an = login(client, "an.gv@lms.test")
    data = {
        "avatar": (io.BytesIO(b"malicious-script"), "hack.php"),
    }
    response = client.post(
        "/users/me/avatar",
        data=data,
        content_type="multipart/form-data",
        headers=auth(an),
    )
    assert response.status_code == 400


# --- Materials ------------------------------------------------------------


def test_materials_lifecycle_and_permissions(client):
    login(client, "admin@lms.test")
    an = login(client, "an.gv@lms.test")  # instructor c1
    chi = login(client, "chi.sv@lms.test")  # student in c1
    em = login(client, "em.sv@lms.test")  # student NOT in c1

    # Instructor uploads material
    data = {
        "title": "Slide Bài 1",
        "file": (io.BytesIO(b"%PDF-1.4 sample pdf content"), "bai1.pdf"),
    }
    upload_res = client.post(
        "/courses/c1/materials",
        data=data,
        content_type="multipart/form-data",
        headers=auth(an),
    )
    assert upload_res.status_code == 201
    mat = upload_res.get_json()
    assert mat["title"] == "Slide Bài 1"
    assert mat["fileName"] == "bai1.pdf"
    mat_id = mat["id"]

    # Student in course lists materials
    list_res = client.get("/courses/c1/materials", headers=auth(chi))
    assert list_res.status_code == 200
    assert len(list_res.get_json()) == 1

    # Student NOT in course cannot list materials
    assert client.get("/courses/c1/materials", headers=auth(em)).status_code == 403

    # Student downloads material
    down_res = client.get(f"/materials/{mat_id}/download", headers=auth(chi))
    assert down_res.status_code == 200
    assert down_res.data == b"%PDF-1.4 sample pdf content"

    # Student NOT in course cannot download
    assert client.get(f"/materials/{mat_id}/download", headers=auth(em)).status_code == 403

    # Student cannot delete material
    assert client.delete(f"/materials/{mat_id}", headers=auth(chi)).status_code == 403

    # Instructor deletes material
    del_res = client.delete(f"/materials/{mat_id}", headers=auth(an))
    assert del_res.status_code == 200
    assert del_res.get_json()["deleted"] is True

    # After delete, download is 404
    assert client.get(f"/materials/{mat_id}/download", headers=auth(chi)).status_code == 404


# --- Submission with file & Grading ---------------------------------------


def test_submission_with_file_and_grading(client):
    an = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")

    # Create assignment
    asg = client.post(
        "/courses/c1/assignments",
        json={"title": "Bài tập 1", "dueAt": 2000000000.0},
        headers=auth(an),
    ).get_json()
    asg_id = asg["id"]

    # Student submits with file
    data = {
        "content": "Em nộp bài qua file đính kèm",
        "file": (io.BytesIO(b"print('hello world')"), "code.py"),
    }
    sub_res = client.post(
        f"/assignments/{asg_id}/submissions",
        data=data,
        content_type="multipart/form-data",
        headers=auth(chi),
    )
    assert sub_res.status_code == 201
    sub = sub_res.get_json()
    assert sub["fileName"] == "code.py"
    sub_id = sub["id"]

    # Student downloads their submission file
    down_sub = client.get(f"/submissions/{sub_id}/download", headers=auth(chi))
    assert down_sub.status_code == 200
    assert down_sub.data == b"print('hello world')"

    # Other student cannot download
    assert client.get(f"/submissions/{sub_id}/download", headers=auth(dung)).status_code == 403

    # Instructor downloads submission file
    assert client.get(f"/submissions/{sub_id}/download", headers=auth(an)).status_code == 200

    # Instructor grades submission
    grade_res = client.post(
        f"/submissions/{sub_id}/grade",
        json={"grade": 9.5, "feedback": "Làm bài rất tốt, code sạch"},
        headers=auth(an),
    )
    assert grade_res.status_code == 200
    graded = grade_res.get_json()
    assert graded["grade"] == 9.5
    assert graded["feedback"] == "Làm bài rất tốt, code sạch"
    assert graded["gradedBy"] == "u2"

    # Student views submissions and sees grade and feedback
    my_subs = client.get("/me/submissions", headers=auth(chi)).get_json()
    assert len(my_subs) == 1
    assert my_subs[0]["grade"] == 9.5
    assert my_subs[0]["feedback"] == "Làm bài rất tốt, code sạch"
