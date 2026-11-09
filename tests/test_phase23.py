"""Phase 2 & 3 — quiz nâng cao, báo cáo, tin nhắn, live, chứng chỉ, huy hiệu."""

import os
import re
import time

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


def post(client, token, path, payload=None):
    return client.post(path, json=payload or {}, headers=auth(token))


def web_login(client, email: str, password: str = PASSWORD):
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.get_data(as_text=True)).group(1)
    client.post(
        "/login",
        data={"csrf_token": token, "email": email, "password": password},
        follow_redirects=True,
    )


def make_quiz(client, instructor, allow=True):
    quiz = post(
        client,
        instructor,
        "/courses/c1/quizzes",
        {
            "title": "Quiz A",
            "description": "",
            "durationMinutes": 10,
            "maxAttempts": 2,
            "allowAnswers": allow,
            "questions": [{"question": "2+2?", "options": ["3", "4"], "correctOption": 1}],
        },
    )
    assert quiz.status_code == 201
    return quiz.get_json()


# --- Phase 2: quiz -------------------------------------------------------


def test_quiz_edit_and_answer_visibility(client):
    instructor = login(client, "an.gv@lms.test")
    student = login(client, "chi.sv@lms.test")
    quiz = make_quiz(client, instructor, allow=True)
    quiz_id = quiz["id"]
    question_id = quiz["questions"][0]["id"]

    assert get(client, student, f"/quizzes/{quiz_id}").get_json().get("allowAnswers") is True
    attempt = post(client, student, f"/quizzes/{quiz_id}/attempts")
    attempt_id = attempt.get_json()["id"]
    submitted = post(
        client,
        student,
        f"/quizzes/{quiz_id}/attempts/{attempt_id}/submit",
        {"answers": {question_id: 1}},
    )
    assert submitted.status_code == 200
    answers = get(client, student, f"/quiz-attempts/{attempt_id}/answers")
    assert answers.status_code == 200
    assert answers.get_json()["answers"][0]["correctOption"] == 1

    updated = client.patch(
        f"/quizzes/{quiz_id}",
        json={
            "title": "Quiz A sửa",
            "description": "",
            "durationMinutes": 15,
            "maxAttempts": 3,
            "allowAnswers": False,
            "questions": [{"question": "3+3?", "options": ["5", "6"], "correctOption": 1}],
        },
        headers=auth(instructor),
    )
    assert updated.status_code == 200
    assert updated.get_json()["title"] == "Quiz A sửa"
    assert updated.get_json()["allowAnswers"] is False


def test_answer_visibility_denied_by_default(client):
    instructor = login(client, "an.gv@lms.test")
    student = login(client, "chi.sv@lms.test")
    quiz = make_quiz(client, instructor, allow=False)
    attempt = post(client, student, f"/quizzes/{quiz['id']}/attempts")
    attempt_id = attempt.get_json()["id"]
    post(
        client,
        student,
        f"/quizzes/{quiz['id']}/attempts/{attempt_id}/submit",
        {"answers": {quiz["questions"][0]["id"]: 1}},
    )
    assert get(client, student, f"/quiz-attempts/{attempt_id}/answers").status_code == 403
    assert get(client, instructor, f"/quiz-attempts/{attempt_id}/answers").status_code == 200


# --- Phase 2: báo cáo ----------------------------------------------------


def test_course_report_and_csv(client):
    instructor = login(client, "an.gv@lms.test")
    student = login(client, "chi.sv@lms.test")
    report = get(client, instructor, "/courses/c1/report")
    assert report.status_code == 200
    assert report.get_json()["students"]
    assert get(client, student, "/courses/c1/report").status_code == 403

    web_login(client, "an.gv@lms.test")
    csv = client.get("/ui/courses/c1/report.csv")
    assert csv.status_code == 200
    assert "text/csv" in csv.content_type
    assert "email" in csv.get_data(as_text=True)


def test_student_progress_and_admin_report(client):
    student = login(client, "chi.sv@lms.test")
    progress = get(client, student, "/me/progress")
    assert progress.status_code == 200
    assert any(item["courseId"] == "c1" for item in progress.get_json())

    admin = login(client, "admin@lms.test")
    summary = get(client, admin, "/admin/report")
    assert summary.status_code == 200
    assert summary.get_json()["users"] >= 6
    assert get(client, login(client, "an.gv@lms.test"), "/admin/report").status_code == 403


# --- Phase 3: tin nhắn ---------------------------------------------------


def test_messages_permissions_and_unread(client):
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")
    em = login(client, "em.sv@lms.test")
    admin = login(client, "admin@lms.test")

    assert post(client, chi, "/messages/u5", {"body": "Chào Dũng"}).status_code == 201
    assert post(client, em, "/messages/u4", {"body": "Lạ"}).status_code == 403
    assert post(client, admin, "/messages/u6", {"body": "Admin nhắn"}).status_code == 201

    conversations = get(client, dung, "/messages")
    assert conversations.status_code == 200
    assert conversations.get_json()[0]["unread"] >= 1

    thread = get(client, dung, "/messages/u4")
    assert thread.status_code == 200
    assert thread.get_json()[0]["body"] == "Chào Dũng"


# --- Phase 3: live session ----------------------------------------------


def test_live_session_create_and_join(client):
    instructor = login(client, "an.gv@lms.test")
    student = login(client, "chi.sv@lms.test")
    created = post(
        client,
        instructor,
        "/courses/c1/live",
        {"title": "Ôn tập", "url": "https://meet.example.com/a", "startsAt": time.time() + 3600},
    )
    assert created.status_code == 201
    session_id = created.get_json()["id"]

    listed = get(client, student, "/courses/c1/live")
    assert listed.status_code == 200 and listed.get_json()[0]["title"] == "Ôn tập"
    assert (
        post(
            client,
            student,
            "/courses/c1/live",
            {"title": "x", "url": "https://x", "startsAt": time.time()},
        ).status_code
        == 403
    )
    assert client.delete(f"/live/{session_id}", headers=auth(instructor)).status_code == 200


# --- Phase 3: bình luận bài học -----------------------------------------


def test_lesson_comments(client):
    instructor = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    dung = login(client, "dung.sv@lms.test")
    lesson = post(client, instructor, "/courses/c1/lessons", {"title": "Bài bình luận"}).get_json()

    created = post(client, chi, f"/lessons/{lesson['id']}/comments", {"body": "Hay quá"})
    assert created.status_code == 201
    comment_id = created.get_json()["id"]
    listed = get(client, chi, f"/lessons/{lesson['id']}/comments")
    assert listed.get_json()[0]["body"] == "Hay quá"
    assert client.delete(f"/lesson-comments/{comment_id}", headers=auth(dung)).status_code == 403
    assert client.delete(f"/lesson-comments/{comment_id}", headers=auth(chi)).status_code == 200


# --- Phase 3: chứng chỉ, xếp hạng, huy hiệu ------------------------------


def test_certificate_auto_issue_and_revoke(client):
    instructor = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    lesson = post(client, instructor, "/courses/c1/lessons", {"title": "Bài cuối"}).get_json()
    assert post(client, chi, f"/lessons/{lesson['id']}/complete").status_code == 200

    mine = get(client, chi, "/me/certificates")
    assert mine.status_code == 200
    certificate = mine.get_json()[0]
    assert certificate["courseId"] == "c1"

    detail = get(client, chi, f"/certificates/{certificate['id']}")
    assert detail.status_code == 200
    assert detail.get_json()["studentName"]

    course_certs = get(client, instructor, "/courses/c1/certificates")
    assert len(course_certs.get_json()) == 1
    assert (
        client.delete(f"/certificates/{certificate['id']}", headers=auth(instructor)).status_code
        == 200
    )


def test_certificate_rule_and_manual_issue(client):
    instructor = login(client, "an.gv@lms.test")
    rule = post(client, instructor, "/courses/c1/certificate-rule", {"minGrade": 5.0})
    assert rule.status_code == 200 and rule.get_json()["certMinGrade"] == 5.0

    issued = post(client, instructor, "/courses/c1/certificates", {"studentId": "u4"})
    assert issued.status_code == 201
    duplicate = post(client, instructor, "/courses/c1/certificates", {"studentId": "u4"})
    assert duplicate.status_code == 409


def test_leaderboard_and_badges(client):
    instructor = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    admin = login(client, "admin@lms.test")

    ranking = get(client, instructor, "/courses/c1/leaderboard")
    assert ranking.status_code == 200
    assert ranking.get_json()[0]["rank"] == 1

    created = post(client, admin, "/admin/badges", {"name": "Ngôi sao", "description": "x"})
    assert created.status_code == 201
    badge_id = created.get_json()["id"]
    assert (
        post(client, admin, f"/admin/badges/{badge_id}/award", {"userId": "u4"}).status_code == 200
    )

    mine = get(client, chi, "/me/badges")
    names = [badge["name"] for badge in mine.get_json()]
    assert "Ngôi sao" in names


def test_auto_badge_after_first_lesson(client):
    instructor = login(client, "an.gv@lms.test")
    chi = login(client, "chi.sv@lms.test")
    lesson = post(client, instructor, "/courses/c1/lessons", {"title": "Bài đầu"}).get_json()
    post(client, chi, f"/lessons/{lesson['id']}/complete")
    names = [badge["name"] for badge in get(client, chi, "/me/badges").get_json()]
    assert "Bài học đầu tiên" in names


# --- UI buttons ----------------------------------------------------------


def test_phase3_ui_pages(client):
    web_login(client, "chi.sv@lms.test")
    assert client.get("/ui/messages").status_code == 200
    assert client.get("/ui/certificates").status_code == 200
    assert client.get("/ui/courses/c1/leaderboard").status_code == 200
    course_page = client.get("/ui/courses/c1").get_data(as_text=True)
    assert "Buổi học trực tuyến" in course_page
