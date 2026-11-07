"""Bước 3.2 — khoá học, yêu cầu mở môn và ghi danh."""

import os

import pytest

from app import course_service, create_app
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


def delete(client, token, path):
    return client.delete(path, headers=auth(token))


def patch(client, token, path, body=None):
    return client.patch(path, json=body, headers=auth(token))


# --- POST /courses (ADMIN) ------------------------------------------------


def test_admin_creates_course_with_uuid(app, client):
    admin = login(client, "admin@lms.test")
    response = post(client, admin, "/courses", {"name": "Mạng máy tính", "instructorId": "u2"})
    assert response.status_code == 201
    course = response.get_json()
    assert course["id"].startswith("c_")
    assert course["id"] not in {"c1", "c2"}
    assert len(course["id"]) >= 32
    assert course["instructorId"] == "u2"

    an = login(client, "an.gv@lms.test")
    assert course["id"] in {item["id"] for item in get(client, an, "/courses").get_json()}


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"name": "X"},
        {"name": "X", "instructorId": "u2", "extra": 1},
        {"name": "", "instructorId": "u2"},
        {"name": "   ", "instructorId": "u2"},
        {"name": "x" * 201, "instructorId": "u2"},
        {"name": 1, "instructorId": "u2"},
        {"name": "X", "instructorId": 2},
    ],
)
def test_create_course_validates_body(client, body):
    response = post(client, login(client, "admin@lms.test"), "/courses", body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


def test_instructor_creates_own_course_and_student_cannot(client):
    an = login(client, "an.gv@lms.test")
    created = post(client, an, "/courses", {"name": "X", "instructorId": "u2"})
    assert created.status_code == 201
    assert created.get_json()["instructorId"] == "u2"

    chi = login(client, "chi.sv@lms.test")
    denied = post(client, chi, "/courses", {"name": "X", "instructorId": "u2"})
    assert denied.status_code == 403
    assert denied.get_json() == {"error": "FORBIDDEN"}


def test_create_course_checks_instructor(client):
    admin = login(client, "admin@lms.test")
    assert post(client, admin, "/courses", {"name": "X", "instructorId": "u99"}).status_code == 404
    # u4 là STUDENT, không được làm giảng viên
    assert post(client, admin, "/courses", {"name": "X", "instructorId": "u4"}).status_code == 400


# --- Yêu cầu mở môn + duyệt ----------------------------------------------


def test_course_request_approval_flow(client):
    an = login(client, "an.gv@lms.test")
    created = post(client, an, "/course-requests", {"name": "Trí tuệ nhân tạo"})
    assert created.status_code == 201
    request = created.get_json()
    assert request["status"] == "PENDING"
    assert request["instructorId"] == "u2"
    assert request["id"].startswith("cr_")

    # Giảng viên chỉ thấy yêu cầu của mình
    binh = login(client, "binh.gv@lms.test")
    assert get(client, binh, "/course-requests").get_json() == []
    assert len(get(client, an, "/course-requests").get_json()) == 1

    admin = login(client, "admin@lms.test")
    assert len(get(client, admin, "/course-requests").get_json()) == 1

    approved = post(client, admin, f"/course-requests/{request['id']}/approve")
    assert approved.status_code == 200
    course = approved.get_json()
    assert course["name"] == "Trí tuệ nhân tạo"
    assert course["instructorId"] == "u2"
    assert course["id"].startswith("c_")

    # Duyệt lại lần nữa: yêu cầu không còn PENDING
    again = post(client, admin, f"/course-requests/{request['id']}/approve")
    assert again.status_code == 409
    assert again.get_json() == {"error": "CONFLICT"}


def test_course_request_rejection(client):
    an = login(client, "an.gv@lms.test")
    request = post(client, an, "/course-requests", {"name": "Môn bị từ chối"}).get_json()
    admin = login(client, "admin@lms.test")

    rejected = post(client, admin, f"/course-requests/{request['id']}/reject")
    assert rejected.status_code == 200
    assert rejected.get_json()["status"] == "REJECTED"
    assert request["id"] in {
        item["id"] for item in get(client, admin, "/course-requests").get_json()
    }

    assert post(client, admin, "/course-requests/cr_missing/approve").status_code == 404
    assert post(client, admin, "/course-requests/cr_missing/reject").status_code == 404


def test_course_requests_permissions(client):
    student = login(client, "chi.sv@lms.test")
    assert post(client, student, "/course-requests", {"name": "X"}).status_code == 403
    assert get(client, student, "/course-requests").status_code == 403

    admin = login(client, "admin@lms.test")
    assert post(client, admin, "/course-requests", {"name": "X"}).status_code == 403

    an = login(client, "an.gv@lms.test")
    request = post(client, an, "/course-requests", {"name": "X"}).get_json()
    assert post(client, an, f"/course-requests/{request['id']}/approve").status_code == 403
    assert post(client, an, f"/course-requests/{request['id']}/reject").status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"name": 1},
        {
            "name": "",
        },
        {"name": "x" * 201, "e": 1},
    ],
)
def test_course_request_validates_body(client, body):
    response = post(client, login(client, "an.gv@lms.test"), "/course-requests", body)
    assert response.status_code == 400


# --- Ghi danh -------------------------------------------------------------


def test_admin_enrolls_student(client, app):
    admin = login(client, "admin@lms.test")
    response = post(client, admin, "/courses/c1/enrollments", {"studentId": "u6"})
    assert response.status_code == 201
    assert response.get_json() == {"courseId": "c1", "studentId": "u6"}

    em = login(client, "em.sv@lms.test")
    assert "c1" in {course["id"] for course in get(client, em, "/courses").get_json()}


def test_enrollment_target_validation(client):
    admin = login(client, "admin@lms.test")
    assert post(client, admin, "/courses/c1/enrollments", {"studentId": "u99"}).status_code == 404
    assert post(client, admin, "/courses/c1/enrollments", {"studentId": "u2"}).status_code == 400
    assert post(client, admin, "/courses/c1/enrollments", {"studentId": "u4"}).status_code == 409


def test_enrollment_404_before_403_and_400_before_404(client):
    # Môn không tồn tại: 404 kể cả khi body sai
    admin = login(client, "admin@lms.test")
    assert post(client, admin, "/courses/c9/enrollments", {"oops": 1}).status_code == 404
    # Body sai: 400 trước khi tra studentId
    assert post(client, admin, "/courses/c1/enrollments", {"oops": 1}).status_code == 400
    # GV môn khác: 403 trước khi validate body
    binh = login(client, "binh.gv@lms.test")
    assert post(client, binh, "/courses/c1/enrollments", {"oops": 1}).status_code == 403


def test_unenroll_revokes_access_immediately(client):
    admin = login(client, "admin@lms.test")
    chi = login(client, "chi.sv@lms.test")
    assert get(client, chi, "/courses/c1").status_code == 200

    assert delete(client, admin, "/courses/c1/enrollments/u4").status_code == 200
    assert get(client, chi, "/courses/c1").status_code == 403
    assert get(client, chi, "/courses/c1/grades").status_code == 403
    assert get(client, chi, "/me/grades").get_json() == []
    assert delete(client, admin, "/courses/c1/enrollments/u4").status_code == 404


def test_students_cannot_manage_enrollments(client):
    chi = login(client, "chi.sv@lms.test")
    assert post(client, chi, "/courses/c1/enrollments", {"studentId": "u5"}).status_code == 403
    assert delete(client, chi, "/courses/c1/enrollments/u5").status_code == 403


# --- Audit ----------------------------------------------------------------


def test_course_writes_are_audited(client, app):
    admin = login(client, "admin@lms.test")
    an = login(client, "an.gv@lms.test")

    request = post(client, an, "/course-requests", {"name": "Kiểm thử"}).get_json()
    post(client, admin, f"/course-requests/{request['id']}/approve")
    post(client, admin, "/courses/c2/enrollments", {"studentId": "u4"})
    delete(client, admin, "/courses/c2/enrollments/u4")

    with open(app.extensions["lms_store"]["audit_log_path"], encoding="utf-8") as audit_file:
        entries = [
            line
            for line in audit_file.read().splitlines()
            if line.strip() and '"action": "LOGIN"' not in line
        ]
    assert len(entries) == 4
    assert "COURSE_REQUEST" in entries[0]
    assert "COURSE_APPROVE" in entries[1]
    assert "ENROLL_STUDENT" in entries[2]
    assert "UNENROLL_STUDENT" in entries[3]


# --- Lớp 4 ----------------------------------------------------------------


def test_course_services_recheck_authorization(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    an = {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"}
    with using_store(app.extensions["lms_store"]):
        with pytest.raises(Forbidden):
            course_service.create_course(chi, "X", "u2")
        # Giảng viên tạo được khoá học nhưng luôn đứng tên chính mình
        course = course_service.create_course(an, "X", "u3")
        assert course["instructorId"] == "u2"
        with pytest.raises(Forbidden):
            course_service.enroll_student(an, "c2", "u4")


def test_course_service_request_directly_is_allowed_for_instructor(app):
    an = {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"}
    with using_store(app.extensions["lms_store"]):
        request = course_service.request_course(an, "Môn tự tạo")
    assert request["status"] == "PENDING"


def test_search_and_filter_courses(client):
    admin = login(client, "admin@lms.test")
    # c1: "Lập trình mạng", instructor: "u2"
    # c2: "Cơ sở dữ liệu", instructor: "u3"
    all_courses = get(client, admin, "/courses").get_json()
    assert len(all_courses) == 2

    # Query search by q
    res_q = get(client, admin, "/courses?q=Web").get_json()
    assert len(res_q) == 1
    assert res_q[0]["id"] == "c1"

    # Query filter by instructor
    res_inst = get(client, admin, "/courses?instructor=u3").get_json()
    assert len(res_inst) == 1
    assert res_inst[0]["id"] == "c2"


def test_update_course(client):
    admin = login(client, "admin@lms.test")
    an = login(client, "an.gv@lms.test")  # instructor of c1
    chi = login(client, "chi.sv@lms.test")  # student

    # Instructor updates their own course
    res = patch(client, an, "/courses/c1", {"name": "Lập trình mạng nâng cao"})
    assert res.status_code == 200
    assert res.get_json()["name"] == "Lập trình mạng nâng cao"

    # Instructor cannot update other instructor's course
    assert patch(client, an, "/courses/c2", {"name": "Hacked"}).status_code == 403

    # Student cannot update course
    assert patch(client, chi, "/courses/c1", {"name": "Hacked"}).status_code == 403

    # Admin can update any course
    res_admin = patch(client, admin, "/courses/c1", {"name": "Lập trình mạng 2026"})
    assert res_admin.status_code == 200
    assert res_admin.get_json()["name"] == "Lập trình mạng 2026"

    # Invalid name
    assert patch(client, an, "/courses/c1", {"name": ""}).status_code == 400


def test_delete_course(client):
    admin = login(client, "admin@lms.test")
    an = login(client, "an.gv@lms.test")

    # Non-admin cannot delete
    assert delete(client, an, "/courses/c2").status_code == 403

    # Admin deletes course
    res = delete(client, admin, "/courses/c2")
    assert res.status_code == 200
    assert res.get_json()["deleted"] is True

    # Deleted course is 404
    assert get(client, admin, "/courses/c2").status_code == 404
    assert delete(client, admin, "/courses/c2").status_code == 404


def test_course_members(client):
    admin = login(client, "admin@lms.test")
    an = login(client, "an.gv@lms.test")  # instructor of c1
    chi = login(client, "chi.sv@lms.test")  # enrolled in c1
    em = login(client, "em.sv@lms.test")  # not enrolled in c1

    # Student enrolled can view members
    res_chi = get(client, chi, "/courses/c1/members")
    assert res_chi.status_code == 200
    members = res_chi.get_json()
    member_ids = {m["id"] for m in members}
    assert "u2" in member_ids  # instructor
    assert "u4" in member_ids  # student chi

    # Student not enrolled cannot view members
    assert get(client, em, "/courses/c1/members").status_code == 403

    # Instructor of course can view members
    assert get(client, an, "/courses/c1/members").status_code == 200
    # Admin can view members
    assert get(client, admin, "/courses/c1/members").status_code == 200
