"""Bước 3.4 — bài tập, nộp bài, hạn nộp và idempotency."""

import os
import time

import pytest

from app import create_app
from app.errors import Forbidden
from app.runtime import using_store

SECRET = "unit-test-secret-with-at-least-32-characters"
PASSWORD = "Lms@2026"
FUTURE = time.time() + 3600
PAST = time.time() - 3600


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


def get(client, token, path):
    return client.get(path, headers=auth(token))


def post(client, token, path, body=None):
    return client.post(path, json=body, headers=auth(token))


def make_assignment(client, token, course_id="c1", **overrides):
    body = {"title": "Bài tập 1", "dueAt": FUTURE}
    body.update(overrides)
    return post(client, token, f"/courses/{course_id}/assignments", body)


# --- Tạo bài tập ----------------------------------------------------------


def test_instructor_creates_assignment_with_uuid(client):
    an = login(client, "an.gv@lms.test")
    response = make_assignment(client, an, description="Nộp file PDF")
    assert response.status_code == 201
    assignment = response.get_json()
    assert assignment["id"].startswith("a_")
    assert len(assignment["id"]) >= 32
    assert assignment["courseId"] == "c1"
    assert assignment["title"] == "Bài tập 1"
    assert assignment["description"] == "Nộp file PDF"
    assert assignment["dueAt"] == pytest.approx(FUTURE, abs=1)


def test_admin_creates_assignment_for_any_course(client):
    admin = login(client, "admin@lms.test")
    assert make_assignment(client, admin, course_id="c2").status_code == 201


def test_assignment_permissions_and_course_404(client):
    binh = login(client, "binh.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    assert make_assignment(client, binh).status_code == 403
    assert make_assignment(client, chi).status_code == 403
    assert make_assignment(client, binh, course_id="c9").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"title": "X"},
        {"title": "X", "dueAt": "khong-phai-ngay"},
        {"title": "X", "dueAt": True},
        {"title": "", "dueAt": FUTURE},
        {"title": "x" * 201, "dueAt": FUTURE},
        {"title": "X", "dueAt": FUTURE, "extra": 1},
        {"title": "X", "dueAt": FUTURE, "description": 1},
    ],
)
def test_assignment_body_validation(client, body):
    response = post(client, login(client, "an.gv@lms.test"), "/courses/c1/assignments", body)
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


# --- Xem bài tập ----------------------------------------------------------


def test_list_assignments_is_scoped(client):
    an = login(client, "an.gv@lms.test")
    created = make_assignment(client, an).get_json()

    chi = login(client, "chi.sv@lms.test")
    assert [item["id"] for item in get(client, chi, "/courses/c1/assignments").get_json()] == [
        created["id"]
    ]

    em = login(client, "em.sv@lms.test")  # không học c1
    assert get(client, em, "/courses/c1/assignments").status_code == 403

    binh = login(client, "binh.gv@lms.test")
    assert get(client, binh, "/courses/c1/assignments").status_code == 403

    admin = login(client, "admin@lms.test")
    assert len(get(client, admin, "/courses/c1/assignments").get_json()) == 1
    assert get(client, admin, "/courses/c9/assignments").status_code == 404


# --- Nộp bài --------------------------------------------------------------


def test_student_submits_and_resubmits_same_content(client):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an).get_json()
    chi = login(client, "chi.sv@lms.test")
    path = f"/assignments/{assignment['id']}/submissions"

    first = post(client, chi, path, {"content": "Bài làm của em"})
    assert first.status_code == 201
    submission = first.get_json()
    assert submission["id"].startswith("s_")
    assert submission["studentId"] == "u4"
    assert submission["content"] == "Bài làm của em"

    again = post(client, chi, path, {"content": "Bài làm của em"})
    assert again.status_code == 200
    assert again.get_json()["id"] == submission["id"]

    changed = post(client, chi, path, {"content": "Bài làm khác"})
    assert changed.status_code == 409
    assert changed.get_json() == {"error": "CONFLICT"}


def test_late_submission_is_forbidden(client):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an, dueAt=PAST).get_json()
    chi = login(client, "chi.sv@lms.test")
    response = post(
        client, chi, f"/assignments/{assignment['id']}/submissions", {"content": "Muộn"}
    )
    assert response.status_code == 403
    assert response.get_json() == {"error": "FORBIDDEN"}


def test_late_check_uses_injected_clock(tmp_path):
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
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an, dueAt=clock["now"] + 60).get_json()
    path = f"/assignments/{assignment['id']}/submissions"

    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")  # Dũng học c1
    assert post(client, chi, path, {"content": "Đúng hạn"}).status_code == 201

    # Token phát trước khi tua đồng hồ để PyJWT không coi iat là tương lai.
    clock["now"] += 61
    response = post(client, dung, path, {"content": "Quá hạn"})
    assert response.status_code == 403
    assert response.get_json() == {"error": "FORBIDDEN"}


def test_submission_permissions(client):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an).get_json()
    path = f"/assignments/{assignment['id']}/submissions"

    # Giảng viên không nộp bài
    assert post(client, an, path, {"content": "x"}).status_code == 403
    # Sinh viên không học môn
    em = login(client, "em.sv@lms.test")
    assert post(client, em, path, {"content": "x"}).status_code == 403
    # Bài tập không tồn tại
    chi = login(client, "chi.sv@lms.test")
    assert (
        post(client, chi, "/assignments/a_missing/submissions", {"content": "x"}).status_code == 404
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"content": ""},
        {"content": "   "},
        {"content": "x" * 5001},
        {"content": 1},
        {"content": "x", "e": 1},
    ],
)
def test_submission_body_validation(client, body):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an).get_json()
    chi = login(client, "chi.sv@lms.test")
    response = post(client, chi, f"/assignments/{assignment['id']}/submissions", body)
    assert response.status_code == 400


# --- Xem bài nộp ----------------------------------------------------------


def test_submission_visibility(client):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an).get_json()
    path = f"/assignments/{assignment['id']}/submissions"

    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")
    post(client, chi, path, {"content": "Của Chi"})
    post(client, dung, path, {"content": "Của Dũng"})

    # GV dạy môn thấy cả lớp
    assert len(get(client, an, path).get_json()) == 2
    # Admin thấy cả lớp
    admin = login(client, "admin@lms.test")
    assert len(get(client, admin, path).get_json()) == 2
    # Sinh viên chỉ thấy bài của mình
    own = get(client, chi, path).get_json()
    assert len(own) == 1
    assert own[0]["studentId"] == "u4"
    # GV môn khác bị chặn
    binh = login(client, "binh.gv@lms.test")
    assert get(client, binh, path).status_code == 403
    # Sinh viên ngoài môn bị chặn
    em = login(client, "em.sv@lms.test")
    assert get(client, em, path).status_code == 403


def test_my_submissions_endpoint(client):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an).get_json()
    chi = login(client, "chi.sv@lms.test")
    post(client, chi, f"/assignments/{assignment['id']}/submissions", {"content": "Của Chi"})

    mine = get(client, chi, "/me/submissions")
    assert mine.status_code == 200
    assert [item["assignmentId"] for item in mine.get_json()] == [assignment["id"]]

    assert get(client, an, "/me/submissions").status_code == 403


# --- Audit + lớp 4 --------------------------------------------------------


def test_assignment_writes_are_audited(client, app):
    an = login(client, "an.gv@lms.test")
    assignment = make_assignment(client, an).get_json()
    chi = login(client, "chi.sv@lms.test")
    post(client, chi, f"/assignments/{assignment['id']}/submissions", {"content": "Bài làm"})
    # gửi lại cùng nội dung không sinh audit mới
    post(client, chi, f"/assignments/{assignment['id']}/submissions", {"content": "Bài làm"})

    with open(app.extensions["lms_store"]["audit_log_path"], encoding="utf-8") as audit_file:
        entries = [
            line
            for line in audit_file.read().splitlines()
            if line.strip() and '"action": "LOGIN"' not in line
        ]
    assert len(entries) == 2
    assert "ASSIGNMENT_CREATE" in entries[0]
    assert "SUBMISSION_CREATE" in entries[1]


def test_assignment_services_recheck_authorization(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    em = {"id": "u6", "email": "em.sv@lms.test", "role": "STUDENT"}
    binh = {"id": "u3", "email": "binh.gv@lms.test", "role": "INSTRUCTOR"}
    with using_store(app.extensions["lms_store"]):
        from app import assignment_service as service

        with pytest.raises(Forbidden):
            service.create_assignment(chi, "c1", "X", "", FUTURE)
        with pytest.raises(Forbidden):
            service.list_assignments(em, "c1")
        with pytest.raises(Forbidden):
            service.create_assignment(binh, "c1", "X", "", FUTURE)
