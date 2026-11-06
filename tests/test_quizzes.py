"""Kiểm thử toàn diện module Bài kiểm tra trắc nghiệm và chấm điểm tự động."""

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
            "DATABASE_PATH": str(tmp_path / "lms.sqlite3"),
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


def test_quizzes_full_lifecycle_and_auto_grading(client):
    admin = login(client, "admin@lms.test")
    an = login(client, "an.gv@lms.test")  # instructor of c1
    chi = login(client, "chi.sv@lms.test")  # student in c1
    em = login(client, "em.sv@lms.test")  # student NOT in c1

    # 1. Student cannot create quiz
    quiz_payload = {
        "title": "Kiểm tra 15 phút HTTP",
        "description": "Trắc nghiệm kiến thức HTTP/1.1 và HTTP/2",
        "durationMinutes": 15,
        "maxAttempts": 2,
        "questions": [
            {
                "question": "Phương thức HTTP nào an toàn (safe)?",
                "options": ["POST", "GET", "DELETE", "PUT"],
                "correctOption": 1,
                "points": 1.0,
            },
            {
                "question": "Mã trạng thái 404 có nghĩa là gì?",
                "options": ["OK", "Forbidden", "Not Found", "Internal Error"],
                "correctOption": 2,
                "points": 1.0,
            },
        ],
    }
    assert client.post("/courses/c1/quizzes", json=quiz_payload, headers=auth(chi)).status_code == 403

    # 2. Instructor of course creates quiz
    create_res = client.post("/courses/c1/quizzes", json=quiz_payload, headers=auth(an))
    assert create_res.status_code == 201
    quiz = create_res.get_json()
    assert quiz["title"] == "Kiểm tra 15 phút HTTP"
    assert len(quiz["questions"]) == 2
    assert "correctOption" in quiz["questions"][0]
    quiz_id = quiz["id"]
    q1_id = quiz["questions"][0]["id"]
    q2_id = quiz["questions"][1]["id"]

    # 3. Student enrolled views quiz -> correctOption must be hidden
    student_quiz_res = client.get(f"/quizzes/{quiz_id}", headers=auth(chi))
    assert student_quiz_res.status_code == 200
    student_quiz = student_quiz_res.get_json()
    assert "correctOption" not in student_quiz["questions"][0]
    assert "correctOption" not in student_quiz["questions"][1]

    # Student NOT in course cannot view quiz
    assert client.get(f"/quizzes/{quiz_id}", headers=auth(em)).status_code == 403

    # 4. Student starts attempt #1
    attempt_res = client.post(f"/quizzes/{quiz_id}/attempts", headers=auth(chi))
    assert attempt_res.status_code == 201
    attempt = attempt_res.get_json()
    assert attempt["attemptNumber"] == 1
    assert attempt["durationMinutes"] == 15
    attempt_id = attempt["id"]

    # Calling start again while attempt is active returns the same active attempt
    attempt_res2 = client.post(f"/quizzes/{quiz_id}/attempts", headers=auth(chi))
    assert attempt_res2.status_code == 201
    assert attempt_res2.get_json()["id"] == attempt_id

    # 5. Student submits attempt: 1 correct, 1 wrong
    # q1 correct: 1 (GET); chosen: 1 -> correct (+1 pt)
    # q2 correct: 2 (Not Found); chosen: 0 (OK) -> wrong (0 pt)
    # Total points: 1/2 -> 5.0 / 10.0
    submit_res = client.post(
        f"/quizzes/{quiz_id}/attempts/{attempt_id}/submit",
        json={"answers": {q1_id: 1, q2_id: 0}},
        headers=auth(chi),
    )
    assert submit_res.status_code == 200
    result = submit_res.get_json()
    assert result["score"] == 5.0
    assert result["maxScore"] == 10.0

    # 6. Cannot resubmit completed attempt
    assert (
        client.post(
            f"/quizzes/{quiz_id}/attempts/{attempt_id}/submit",
            json={"answers": {q1_id: 1}},
            headers=auth(chi),
        ).status_code
        == 409
    )

    # 7. Student starts attempt #2 (since maxAttempts=2)
    attempt2_res = client.post(f"/quizzes/{quiz_id}/attempts", headers=auth(chi))
    assert attempt2_res.status_code == 201
    attempt2 = attempt2_res.get_json()
    assert attempt2["attemptNumber"] == 2
    attempt2_id = attempt2["id"]

    # Submit attempt #2 with 100% correct answers (q1: 1, q2: 2) -> Score: 10.0
    submit2_res = client.post(
        f"/quizzes/{quiz_id}/attempts/{attempt2_id}/submit",
        json={"answers": {q1_id: 1, q2_id: 2}},
        headers=auth(chi),
    )
    assert submit2_res.status_code == 200
    assert submit2_res.get_json()["score"] == 10.0

    # 8. Student tries attempt #3 -> Conflict (max attempts reached)
    assert client.post(f"/quizzes/{quiz_id}/attempts", headers=auth(chi)).status_code == 409

    # 9. List attempts
    # Student views own attempts
    chi_attempts = client.get(f"/quizzes/{quiz_id}/attempts", headers=auth(chi)).get_json()
    assert len(chi_attempts) == 2
    assert chi_attempts[0]["score"] == 5.0
    assert chi_attempts[1]["score"] == 10.0

    # Instructor views all attempts
    gv_attempts = client.get(f"/quizzes/{quiz_id}/attempts", headers=auth(an)).get_json()
    assert len(gv_attempts) == 2

    # 10. Instructor deletes quiz
    del_res = client.delete(f"/quizzes/{quiz_id}", headers=auth(an))
    assert del_res.status_code == 200
    assert del_res.get_json()["deleted"] is True

    # After delete -> 404
    assert client.get(f"/quizzes/{quiz_id}", headers=auth(an)).status_code == 404


def test_quiz_validation_errors(client):
    an = login(client, "an.gv@lms.test")

    # Missing questions
    assert (
        client.post(
            "/courses/c1/quizzes",
            json={"title": "Q", "durationMinutes": 10, "questions": []},
            headers=auth(an),
        ).status_code
        == 400
    )

    # Invalid duration
    assert (
        client.post(
            "/courses/c1/quizzes",
            json={
                "title": "Q",
                "durationMinutes": -5,
                "questions": [
                    {"question": "A?", "options": ["1", "2"], "correctOption": 0}
                ],
            },
            headers=auth(an),
        ).status_code
        == 400
    )

    # Invalid correctOption index
    assert (
        client.post(
            "/courses/c1/quizzes",
            json={
                "title": "Q",
                "durationMinutes": 10,
                "questions": [
                    {"question": "A?", "options": ["1", "2"], "correctOption": 5}
                ],
            },
            headers=auth(an),
        ).status_code
        == 400
    )
