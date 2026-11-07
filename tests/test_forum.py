"""Bước 3.5 — thông báo, thread, comment: quyền, văn bản thuần và audit."""

import os

import pytest

from app import create_app, forum_service
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


def login(client, email: str) -> str:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def get(client, token, path):
    return client.get(path, headers=auth(token))


def post(client, token, path, body=None):
    return client.post(path, json=body, headers=auth(token))


def delete(client, token, path):
    return client.delete(path, headers=auth(token))


def make_thread(client, token, course_id="c1", title="Thảo luận 1"):
    return post(
        client, token, f"/courses/{course_id}/threads", {"title": title, "body": "Nội dung"}
    )


# --- Announcement ---------------------------------------------------------


def test_instructor_creates_announcement(client):
    an = login(client, "an.gv@lms.test")
    response = post(
        client, an, "/courses/c1/announcements", {"title": "Lịch thi", "body": "Thi tuần 12"}
    )
    assert response.status_code == 201
    announcement = response.get_json()
    assert announcement["id"].startswith("an_")
    assert announcement["title"] == "Lịch thi"
    assert announcement["createdBy"] == "u2"


def test_admin_creates_announcement_but_other_instructor_cannot(client):
    admin = login(client, "admin@lms.test")
    assert (
        post(client, admin, "/courses/c2/announcements", {"title": "T", "body": "B"}).status_code
        == 201
    )
    binh = login(client, "binh.gv@lms.test")
    assert (
        post(client, binh, "/courses/c1/announcements", {"title": "T", "body": "B"}).status_code
        == 403
    )
    chi = login(client, "chi.sv@lms.test")
    assert (
        post(client, chi, "/courses/c1/announcements", {"title": "T", "body": "B"}).status_code
        == 403
    )


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"title": "T"},
        {"body": "B"},
        {"title": "", "body": "B"},
        {"title": "T", "body": ""},
        {"title": "T", "body": "B", "extra": 1},
        {"title": 1, "body": "B"},
        {"title": "T", "body": "x" * 5001},
    ],
)
def test_announcement_body_validation(client, body):
    response = post(client, login(client, "an.gv@lms.test"), "/courses/c1/announcements", body)
    assert response.status_code == 400


def test_announcement_visibility(client):
    an = login(client, "an.gv@lms.test")
    post(client, an, "/courses/c1/announcements", {"title": "T", "body": "B"})

    chi = login(client, "chi.sv@lms.test")
    assert len(get(client, chi, "/courses/c1/announcements").get_json()) == 1

    em = login(client, "em.sv@lms.test")
    assert get(client, em, "/courses/c1/announcements").status_code == 403

    binh = login(client, "binh.gv@lms.test")
    assert get(client, binh, "/courses/c1/announcements").status_code == 403

    assert get(client, chi, "/courses/c9/announcements").status_code == 404


def test_only_course_staff_deletes_announcement(client, app):
    an = login(client, "an.gv@lms.test")
    announcement = post(
        client, an, "/courses/c1/announcements", {"title": "T", "body": "B"}
    ).get_json()

    chi = login(client, "chi.sv@lms.test")
    assert delete(client, chi, f"/announcements/{announcement['id']}").status_code == 403
    binh = login(client, "binh.gv@lms.test")
    assert delete(client, binh, f"/announcements/{announcement['id']}").status_code == 403

    assert delete(client, an, f"/announcements/{announcement['id']}").status_code == 200
    assert get(client, chi, "/courses/c1/announcements").get_json() == []
    assert delete(client, an, f"/announcements/{announcement['id']}").status_code == 404


# --- Thread ---------------------------------------------------------------


def test_enrolled_student_and_staff_create_thread(client):
    chi = login(client, "chi.sv@lms.test")
    created = make_thread(client, chi)
    assert created.status_code == 201
    assert created.get_json()["id"].startswith("th_")

    an = login(client, "an.gv@lms.test")
    assert make_thread(client, an, title="GV mở thread").status_code == 201

    admin = login(client, "admin@lms.test")
    assert make_thread(client, admin, title="Admin mở thread").status_code == 201

    em = login(client, "em.sv@lms.test")
    assert make_thread(client, em).status_code == 403


def test_thread_body_validation(client):
    chi = login(client, "chi.sv@lms.test")
    for body in (
        None,
        {},
        {"title": "T"},
        {"title": "x" * 201, "body": "B"},
        {"title": "T", "body": "B", "x": 1},
    ):
        assert post(client, chi, "/courses/c1/threads", body).status_code == 400
    assert post(client, chi, "/courses/c9/threads", {"title": "T", "body": "B"}).status_code == 404


def test_thread_delete_allows_owner_and_course_staff(client):
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")
    thread = make_thread(client, chi).get_json()
    post(client, chi, f"/threads/{thread['id']}/comments", {"body": "Bình luận"})

    # Sinh viên khác không xoá được nội dung của người khác
    assert delete(client, dung, f"/threads/{thread['id']}").status_code == 403

    # Chủ sở hữu xoá được nội dung của chính mình (kèm bình luận)
    assert delete(client, chi, f"/threads/{thread['id']}").status_code == 200
    assert get(client, chi, f"/threads/{thread['id']}/comments").status_code == 404

    # Giảng viên phụ trách vẫn xoá được nội dung của lớp
    other = make_thread(client, chi).get_json()
    an = login(client, "an.gv@lms.test")
    assert delete(client, an, f"/threads/{other['id']}").status_code == 200


# --- Comment --------------------------------------------------------------


def test_comments_require_course_membership(client):
    chi = login(client, "chi.sv@lms.test")
    thread = make_thread(client, chi).get_json()

    em = login(client, "em.sv@lms.test")
    assert post(client, em, f"/threads/{thread['id']}/comments", {"body": "X"}).status_code == 403
    assert get(client, em, f"/threads/{thread['id']}/comments").status_code == 403

    assert post(client, chi, "/threads/th_missing/comments", {"body": "X"}).status_code == 404


def test_comment_body_is_plain_text_and_limits(client):
    chi = login(client, "chi.sv@lms.test")
    thread = make_thread(client, chi).get_json()
    path = f"/threads/{thread['id']}/comments"

    raw = "<script>alert('x')</script> & <b>đậm</b>"
    created = post(client, chi, path, {"body": raw})
    assert created.status_code == 201
    assert created.get_json()["body"] == raw

    listed = get(client, chi, path).get_json()
    assert listed[0]["body"] == raw

    for body in (None, {}, {"body": ""}, {"body": "x" * 2001}, {"body": "X", "extra": 1}):
        assert post(client, chi, path, body).status_code == 400


def test_comment_delete_allows_owner_and_admin(client):
    chi = login(client, "chi.sv@lms.test")
    thread = make_thread(client, chi).get_json()
    comment = post(client, chi, f"/threads/{thread['id']}/comments", {"body": "Của Chi"}).get_json()

    # Chủ sở hữu xoá được bình luận của mình
    assert delete(client, chi, f"/comments/{comment['id']}").status_code == 200

    second = post(
        client, chi, f"/threads/{thread['id']}/comments", {"body": "Của Chi 2"}
    ).get_json()
    binh = login(client, "binh.gv@lms.test")  # không phụ trách c1
    assert delete(client, binh, f"/comments/{second['id']}").status_code == 403

    admin = login(client, "admin@lms.test")
    assert delete(client, admin, f"/comments/{second['id']}").status_code == 200
    assert delete(client, admin, f"/comments/{second['id']}").status_code == 404


# --- Audit + lớp 4 --------------------------------------------------------


def test_forum_writes_are_audited(client, app):
    an = login(client, "an.gv@lms.test")
    announcement = post(
        client, an, "/courses/c1/announcements", {"title": "T", "body": "B"}
    ).get_json()
    thread = make_thread(client, an).get_json()
    comment = post(client, an, f"/threads/{thread['id']}/comments", {"body": "C"}).get_json()
    delete(client, an, f"/comments/{comment['id']}")
    delete(client, an, f"/threads/{thread['id']}")
    delete(client, an, f"/announcements/{announcement['id']}")

    with open(app.extensions["lms_store"]["audit_log_path"], encoding="utf-8") as audit_file:
        entries = [
            line
            for line in audit_file.read().splitlines()
            if line.strip() and '"action": "LOGIN"' not in line
        ]
    actions = [entry for entry in entries]
    assert len(actions) == 6
    for marker in (
        "ANNOUNCEMENT_CREATE",
        "THREAD_CREATE",
        "COMMENT_CREATE",
        "COMMENT_DELETE",
        "THREAD_DELETE",
        "ANNOUNCEMENT_DELETE",
    ):
        assert any(marker in line for line in actions), marker


def test_forum_services_recheck_authorization(app):
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    em = {"id": "u6", "email": "em.sv@lms.test", "role": "STUDENT"}
    with using_store(app.extensions["lms_store"]):
        with pytest.raises(Forbidden):
            forum_service.create_announcement(chi, "c1", "T", "B")
        with pytest.raises(Forbidden):
            forum_service.list_threads(em, "c1")
        with pytest.raises(Forbidden):
            forum_service.create_thread(em, "c1", "T", "B")
