"""Giai đoạn 3 — ma trận quyền cho các endpoint mở rộng, IDOR và token vô hiệu."""

import os
import time

import pytest

from app import admin_service, course_service, create_app
from app.services import using_store

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


def get(client, token: str, path: str):
    return client.get(path, headers=auth(token))


def post(client, token: str, path: str, body=None):
    return client.post(path, json=body, headers=auth(token))


def delete(client, token: str, path: str):
    return client.delete(path, headers=auth(token))


def patch(client, token: str, path: str, body=None):
    return client.patch(path, json=body, headers=auth(token))


# --- GET /courses ---------------------------------------------------------


def test_course_list_is_scoped_by_role(client):
    assert {
        c["id"] for c in get(client, login(client, "admin@lms.test"), "/courses").get_json()
    } == {
        "c1",
        "c2",
    }
    instructor = get(client, login(client, "an.gv@lms.test"), "/courses").get_json()
    assert [c["id"] for c in instructor] == ["c1"]
    student = get(client, login(client, "chi.sv@lms.test"), "/courses").get_json()
    assert [c["id"] for c in student] == ["c1"]
    other_student = get(client, login(client, "em.sv@lms.test"), "/courses").get_json()
    assert [c["id"] for c in other_student] == ["c2"]


def test_course_list_items_have_only_contract_fields(client):
    course = get(client, login(client, "em.sv@lms.test"), "/courses").get_json()[0]
    assert set(course) == {"id", "name", "instructorId"}


# --- GET /courses/<id> ----------------------------------------------------


def test_course_detail_matrix(client):
    admin = login(client, "admin@lms.test")
    assert get(client, admin, "/courses/c1").status_code == 200
    assert get(client, admin, "/courses/c9").status_code == 404

    an = login(client, "an.gv@lms.test")
    assert get(client, an, "/courses/c1").status_code == 200
    assert get(client, an, "/courses/c2").status_code == 403
    assert get(client, an, "/courses/c9").status_code == 404

    chi = login(client, "chi.sv@lms.test")
    assert get(client, chi, "/courses/c1").status_code == 200
    assert get(client, chi, "/courses/c2").status_code == 403


# --- POST/DELETE enrollments ---------------------------------------------


def test_instructor_adds_student_to_own_course(app, client):
    token = login(client, "an.gv@lms.test")
    response = post(client, token, "/courses/c1/enrollments", {"studentId": "u6"})
    assert response.status_code == 201
    assert response.get_json() == {"courseId": "c1", "studentId": "u6"}
    assert app.extensions["lms_store"]["connection"].execute(
        "SELECT score FROM enrollments WHERE course_id='c1' AND student_id='u6'"
    ).fetchone() == (0.0,)


def test_instructor_cannot_manage_other_course(client):
    token = login(client, "binh.gv@lms.test")
    assert post(client, token, "/courses/c1/enrollments", {"studentId": "u6"}).status_code == 403
    assert delete(client, token, "/courses/c1/enrollments/u4").status_code == 403
    assert post(client, token, "/courses/c1/enrollments", {"studentId": "u6"}).get_json() == {
        "error": "FORBIDDEN"
    }


def test_student_cannot_manage_enrollments(client):
    token = login(client, "chi.sv@lms.test")
    assert post(client, token, "/courses/c1/enrollments", {"studentId": "u5"}).status_code == 403
    assert delete(client, token, "/courses/c1/enrollments/u5").status_code == 403


def test_management_404_precedes_403(client):
    # Môn không tồn tại: 404 kể cả khi người gọi là sinh viên (sai vai trò).
    student = login(client, "chi.sv@lms.test")
    assert post(client, student, "/courses/c9/enrollments", {"studentId": "u4"}).status_code == 404

    instructor = login(client, "binh.gv@lms.test")
    assert (
        post(client, instructor, "/courses/c9/enrollments", {"studentId": "u4"}).status_code == 404
    )


def test_enrollment_body_validation(client):
    token = login(client, "an.gv@lms.test")
    for body in (
        None,
        {"studentId": "u6", "extra": 1},
        {},
        {"studentId": 6},
        {"studentId": ""},
        ["u6"],
    ):
        response = post(client, token, "/courses/c1/enrollments", body)
        assert response.status_code == 400, body
        assert response.get_json() == {"error": "VALIDATION_ERROR"}

    assert post(client, token, "/courses/c1/enrollments", {"studentId": "u99"}).status_code == 404
    assert post(client, token, "/courses/c1/enrollments", {"studentId": "u4"}).status_code == 409


def test_remove_enrollment_and_second_remove_is_404(app, client):
    token = login(client, "admin@lms.test")
    assert delete(client, token, "/courses/c1/enrollments/u5").status_code == 200
    assert (
        app.extensions["lms_store"]["connection"]
        .execute("SELECT 1 FROM enrollments WHERE course_id='c1' AND student_id='u5'")
        .fetchone()
        is None
    )
    assert delete(client, token, "/courses/c1/enrollments/u5").status_code == 404


# --- GET /me/grades -------------------------------------------------------


def test_student_reads_own_grades_only(client):
    chi = login(client, "chi.sv@lms.test")
    response = get(client, chi, "/me/grades")
    assert response.status_code == 200
    assert response.get_json() == [{"courseId": "c1", "courseName": "Lập trình Web", "score": 7.5}]
    for email in ("admin@lms.test", "an.gv@lms.test"):
        assert get(client, login(client, email), "/me/grades").status_code == 403


# --- GET /admin/users + PATCH role ---------------------------------------


def test_admin_lists_users_without_hashes(client):
    token = login(client, "admin@lms.test")
    response = get(client, token, "/admin/users")
    assert response.status_code == 200
    users = response.get_json()
    assert len(users) == 6
    assert {user["id"] for user in users} == {"u1", "u2", "u3", "u4", "u5", "u6"}
    assert all(set(user) == {"id", "email", "name", "role", "locked"} for user in users)
    text = response.get_data(as_text=True).lower()
    assert "pw_hash" not in text and "password" not in text


def test_non_admin_cannot_list_users(client):
    for email in ("an.gv@lms.test", "chi.sv@lms.test"):
        response = get(client, login(client, email), "/admin/users")
        assert response.status_code == 403
        assert response.get_json() == {"error": "FORBIDDEN"}


def test_role_change_validation_and_404(client):
    admin = login(client, "admin@lms.test")
    assert (
        patch(
            client, login(client, "an.gv@lms.test"), "/admin/users/u4/role", {"role": "ADMIN"}
        ).status_code
        == 403
    )
    assert patch(client, admin, "/admin/users/u4/role", {"role": "TEACHER"}).status_code == 400
    assert (
        patch(client, admin, "/admin/users/u4/role", {"role": "ADMIN", "extra": 1}).status_code
        == 400
    )
    assert patch(client, admin, "/admin/users/u4/role", {"role": "admin"}).status_code == 400
    assert patch(client, admin, "/admin/users/u99/role", {"role": "ADMIN"}).status_code == 404


def test_role_change_updates_store_and_audit(client, app):
    admin = login(client, "admin@lms.test")
    response = patch(client, admin, "/admin/users/u4/role", {"role": "INSTRUCTOR"})
    assert response.status_code == 200
    assert response.get_json()["role"] == "INSTRUCTOR"
    assert app.extensions["lms_store"]["users"]["u4"]["role"] == "INSTRUCTOR"

    with open(app.extensions["lms_store"]["audit_log_path"], encoding="utf-8") as audit_file:
        entries = [line for line in audit_file.read().splitlines() if "ROLE_CHANGE" in line]
    assert len(entries) == 1


def test_admin_cannot_demote_sole_admin(client):
    admin = login(client, "admin@lms.test")
    response = patch(client, admin, "/admin/users/u1/role", {"role": "STUDENT"})
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_admin_cannot_change_own_role_even_with_another_admin(client):
    admin = login(client, "admin@lms.test")
    assert patch(client, admin, "/admin/users/u2/role", {"role": "ADMIN"}).status_code == 200
    response = patch(client, admin, "/admin/users/u1/role", {"role": "INSTRUCTOR"})
    assert response.status_code == 400


# --- POST /auth/logout và token vô hiệu ----------------------------------


def test_logout_invalidates_the_used_token(client):
    token = login(client, "chi.sv@lms.test")
    assert get(client, token, "/me").status_code == 200
    time.sleep(1.05)  # mốc vô hiệu tính theo giây: token phải thuộc giây trước đó
    assert post(client, token, "/auth/logout").status_code == 200
    assert get(client, token, "/me").status_code == 401

    fresh = login(client, "chi.sv@lms.test")
    assert get(client, fresh, "/me").status_code == 200


def test_logout_requires_authentication(client):
    assert client.post("/auth/logout").status_code == 401
    assert client.post("/auth/logout", headers=auth("khong-phai-token")).status_code == 401


def test_role_change_invalidates_existing_tokens(client):
    chi = login(client, "chi.sv@lms.test")
    admin = login(client, "admin@lms.test")
    time.sleep(1.05)  # token của Chi phải thuộc giây trước mốc vô hiệu
    assert patch(client, admin, "/admin/users/u4/role", {"role": "INSTRUCTOR"}).status_code == 200

    assert get(client, chi, "/me").status_code == 401
    relogged = login(client, "chi.sv@lms.test")
    assert get(client, relogged, "/me").get_json()["role"] == "INSTRUCTOR"


# --- Lớp 4: kiểm tra trực tiếp ở service ---------------------------------


def test_services_recheck_authorization_without_routes(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    an = {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"}

    with using_store(app.extensions["lms_store"]):
        from app.errors import Forbidden

        with pytest.raises(Forbidden):
            course_service.enroll_student(chi, "c1", "u5")
        with pytest.raises(Forbidden):
            admin_service.list_users(chi)
        with pytest.raises(Forbidden):
            admin_service.change_role(chi, "u4", "ADMIN")
        with pytest.raises(Forbidden):
            course_service.get_course(an, "c2")
        with pytest.raises(Forbidden):
            course_service.my_grades(an)


# --- Guest ---------------------------------------------------------------


def test_guest_is_rejected_by_the_gate(client):
    assert client.get("/courses").status_code == 401
    assert client.get("/me/grades").status_code == 401
    assert client.get("/admin/users").status_code == 401
    assert client.get("/courses/c9").status_code == 401


# --- Đồng hồ có thể inject ------------------------------------------------


def test_lockout_expires_with_injected_clock(tmp_path):
    clock = {"now": time.time()}
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "DATABASE_URL": os.environ["TEST_DATABASE_URL"],
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "CLOCK": lambda: clock["now"],
        }
    )
    client = app.test_client()

    for _ in range(5):
        response = client.post(
            "/auth/login", json={"email": "dung.sv@lms.test", "password": "sai-mat-khau"}
        )
        assert response.status_code == 401

    locked = client.post("/auth/login", json={"email": "dung.sv@lms.test", "password": PASSWORD})
    assert locked.status_code == 429

    clock["now"] += 15 * 60 + 1
    unlocked = client.post("/auth/login", json={"email": "dung.sv@lms.test", "password": PASSWORD})
    assert unlocked.status_code == 200
