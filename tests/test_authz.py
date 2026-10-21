import base64
import json
import time

import pytest
from flask import abort, jsonify

from app import create_app
from app.errors import Forbidden, NotFound, Unauthenticated, ValidationError
from app import store as store_module
from app.guards import require_role
from app.schemas import validate_grade_body, validate_score
from app.services import update_grade, using_store


SECRET = "unit-test-secret-with-at-least-32-characters"


@pytest.fixture
def app(tmp_path, monkeypatch):
    audit_path = tmp_path / "audit.log"
    monkeypatch.setenv("JWT_SECRET", "environment-secret-that-is-long-enough")
    monkeypatch.setenv("TOKEN_TTL_SECONDS", "4")
    monkeypatch.setenv("AUDIT_LOG_PATH", str(tmp_path / "environment-audit.log"))
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "TOKEN_TTL_SECONDS": 900,
            "AUDIT_LOG_PATH": str(audit_path),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, password="Lms@2026"):
    response = client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return response.get_json()["accessToken"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_A1_unknown_and_wrong_password_have_identical_responses(client):
    unknown = client.post(
        "/auth/login",
        json={"email": "nobody@lms.test", "password": "wrong-password"},
    )
    wrong = client.post(
        "/auth/login",
        json={"email": "chi.sv@lms.test", "password": "wrong-password"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json() == {"error": "INVALID_CREDENTIALS"}


def test_A2_me_requires_a_token(client):
    response = client.get("/me")
    assert response.status_code == 401
    assert response.get_json() == {"error": "UNAUTHENTICATED"}


def test_A3_changing_subject_without_resigning_is_rejected(client):
    token = login(client, "chi.sv@lms.test")
    header, payload, signature = token.split(".")
    claims = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    claims["sub"] = "u1"
    changed_payload = base64.urlsafe_b64encode(
        json.dumps(claims, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    forged = f"{header}.{changed_payload}.{signature}"

    response = client.get("/me", headers=auth(forged))
    assert response.status_code == 401
    assert response.get_json() == {"error": "UNAUTHENTICATED"}


def test_A4_none_algorithm_token_is_rejected(client):
    token = login(client, "chi.sv@lms.test")
    _, payload, _ = token.split(".")
    none_header = base64.urlsafe_b64encode(
        b'{"alg":"none","typ":"JWT"}'
    ).rstrip(b"=").decode()
    unsigned = f"{none_header}.{payload}."

    response = client.get("/me", headers=auth(unsigned))
    assert response.status_code == 401
    assert response.get_json() == {"error": "UNAUTHENTICATED"}


def test_A5_expired_token_is_rejected(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "JWT_SECRET": SECRET,
            "TOKEN_TTL_SECONDS": 1,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
        }
    )
    client = app.test_client()
    token = login(client, "chi.sv@lms.test")
    time.sleep(2)
    response = client.get("/me", headers=auth(token))
    assert response.status_code == 401
    assert response.get_json() == {"error": "UNAUTHENTICATED"}


def test_A6_responses_never_expose_password_fields_or_values(client):
    token = login(client, "chi.sv@lms.test")
    responses = [
        client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "wrong"},
        ),
        client.get("/me", headers=auth(token)),
    ]
    for response in responses:
        assert response.status_code in (200, 401)
        body = response.get_json()
        assert not ({"password", "password_hash", "passwordHash"} & set(body))
        assert "Lms@2026" not in response.get_data(as_text=True)


def test_A7_student_sees_only_own_course_grade(client):
    token = login(client, "chi.sv@lms.test")
    response = client.get("/courses/c1/grades", headers=auth(token))
    assert response.status_code == 200
    assert response.get_json() == [{"studentId": "u4", "score": 7.5}]


def test_A8_student_not_enrolled_in_course_is_forbidden(client):
    token = login(client, "chi.sv@lms.test")
    response = client.get("/courses/c2/grades", headers=auth(token))
    assert response.status_code == 403
    assert response.get_json() == {"error": "FORBIDDEN"}


def test_A9_student_cannot_update_grade(client):
    token = login(client, "chi.sv@lms.test")
    response = client.put(
        "/courses/c1/grades/u4", json={"score": 10}, headers=auth(token)
    )
    assert response.status_code == 403
    assert response.get_json() == {"error": "FORBIDDEN"}


def test_A10_other_instructor_cannot_update_grade(client):
    token = login(client, "binh.gv@lms.test")
    response = client.put(
        "/courses/c1/grades/u4", json={"score": 0}, headers=auth(token)
    )
    assert response.status_code == 403
    assert response.get_json() == {"error": "FORBIDDEN"}


def test_A11_admin_cannot_update_grade(client):
    token = login(client, "admin@lms.test")
    response = client.put(
        "/courses/c1/grades/u4", json={"score": 10}, headers=auth(token)
    )
    assert response.status_code == 403
    assert response.get_json() == {"error": "FORBIDDEN"}


@pytest.mark.parametrize(
    "body",
    [
        {"score": 11},
        {"score": -1},
        {"score": "10"},
        {"score": True},
        {"score": 9, "courseId": "c2"},
        {"score": float("nan")},
        {"score": float("inf")},
        {"score": 10**400},
    ],
)
def test_A12_invalid_score_bodies_are_rejected(client, body):
    token = login(client, "an.gv@lms.test")
    response = client.put(
        "/courses/c1/grades/u4", json=body, headers=auth(token)
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "VALIDATION_ERROR"}


@pytest.mark.parametrize("score", [0, 10, 7.5])
def test_score_schema_accepts_finite_numeric_values(score):
    assert validate_score(score) == score
    assert validate_grade_body({"score": score}) == score


def test_score_schema_rejects_bool_and_extra_or_missing_fields():
    for score in (True, False):
        with pytest.raises(ValidationError):
            validate_score(score)
    for body in ({}, {"score": 1, "extra": "field"}, None, []):
        with pytest.raises(ValidationError):
            validate_grade_body(body)


def test_A13_instructor_cannot_update_unenrolled_student(client):
    token = login(client, "an.gv@lms.test")
    response = client.put(
        "/courses/c1/grades/u6", json={"score": 5}, headers=auth(token)
    )
    assert response.status_code == 404
    assert response.get_json() == {"error": "NOT_FOUND"}


def test_A14_instructor_update_is_visible_to_student(client):
    instructor_token = login(client, "an.gv@lms.test")
    update = client.put(
        "/courses/c1/grades/u4",
        json={"score": 9},
        headers=auth(instructor_token),
    )
    student_token = login(client, "chi.sv@lms.test")
    read = client.get("/courses/c1/grades", headers=auth(student_token))
    assert update.status_code == 200
    assert update.get_json() == {"courseId": "c1", "studentId": "u4", "score": 9}
    assert read.status_code == 200
    assert read.get_json() == [{"studentId": "u4", "score": 9}]


def test_A15_removing_route_guard_and_direct_service_call_stay_safe(app):
    guarded_view = app.view_functions["put_grade"]
    app.view_functions["put_grade"] = guarded_view.__wrapped__
    client = app.test_client()
    for email in ("chi.sv@lms.test", "binh.gv@lms.test", "admin@lms.test"):
        token = login(client, email)
        response = client.put(
            "/courses/c1/grades/u4",
            json={"score": 10},
            headers=auth(token),
        )
        assert response.status_code == 403

    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with pytest.raises(Forbidden):
        update_grade(chi, "c1", "u4", 10)


def test_update_service_checks_course_before_actor_role(app):
    student = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with using_store(app.extensions["lms_store"]):
        with pytest.raises(NotFound):
            update_grade(student, "missing-course", "u4", 10)


def test_A16_new_route_without_guard_still_requires_authentication(app):
    app.add_url_rule(
        "/debug",
        endpoint="debug",
        view_func=lambda: jsonify({"debug": True}),
        methods=["GET"],
    )
    response = app.test_client().get("/debug")
    assert response.status_code == 401
    assert response.get_json() == {"error": "UNAUTHENTICATED"}


def test_gate_authenticates_unknown_routes_before_404(app):
    client = app.test_client()
    unauthenticated = client.get("/no-such-route")
    assert unauthenticated.status_code == 401
    assert unauthenticated.get_json() == {"error": "UNAUTHENTICATED"}

    token = login(client, "chi.sv@lms.test")
    authenticated = client.get("/no-such-route", headers=auth(token))
    assert authenticated.status_code == 404
    assert authenticated.get_json() == {"error": "NOT_FOUND"}


def test_role_guard_rejects_request_without_actor(app):
    guarded = require_role("ADMIN")(lambda: jsonify({"ok": True}))
    with app.test_request_context("/guarded"):
        with pytest.raises(Unauthenticated):
            guarded()


def test_A17_missing_secret_prevents_app_creation(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        create_app()


def test_A18_fifth_failure_locks_account_even_for_correct_password(client):
    for _ in range(5):
        response = client.post(
            "/auth/login",
            json={"email": "dung.sv@lms.test", "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert response.get_json() == {"error": "INVALID_CREDENTIALS"}

    locked = client.post(
        "/auth/login",
        json={"email": "dung.sv@lms.test", "password": "Lms@2026"},
    )
    assert locked.status_code == 429
    assert locked.get_json() == {"error": "ACCOUNT_LOCKED"}


def test_failed_attempts_are_counted_for_unknown_emails(client, app):
    email = "not-a-real-account@lms.test"
    for _ in range(5):
        response = client.post(
            "/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert response.status_code == 401
        assert response.get_json() == {"error": "INVALID_CREDENTIALS"}

    assert app.extensions["lms_store"]["attempts"][email]["fails"] == 5
    locked = client.post(
        "/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert locked.status_code == 429
    assert locked.get_json() == {"error": "ACCOUNT_LOCKED"}


def test_successful_login_resets_failed_attempt_counter(client, app):
    email = "chi.sv@lms.test"
    for _ in range(4):
        response = client.post(
            "/auth/login", json={"email": email, "password": "wrong-password"}
        )
        assert response.status_code == 401

    assert app.extensions["lms_store"]["attempts"][email]["fails"] == 4
    assert login(client, email)
    assert app.extensions["lms_store"]["attempts"][email]["fails"] == 0


def test_A19_audit_logs_one_denial_and_one_update_without_credentials(app):
    client = app.test_client()
    student_token = login(client, "chi.sv@lms.test")
    instructor_token = login(client, "an.gv@lms.test")
    denied = client.put(
        "/courses/c1/grades/u4",
        json={"score": 10},
        headers=auth(student_token),
    )
    updated = client.put(
        "/courses/c1/grades/u4",
        json={"score": 9},
        headers=auth(instructor_token),
    )
    assert denied.status_code == 403
    assert updated.status_code == 200

    audit_path = app.extensions["lms_store"]["audit_log_path"]
    with open(audit_path, encoding="utf-8") as audit_file:
        lines = audit_file.read().splitlines()
    assert len(lines) == 2
    entries = [json.loads(line) for line in lines]
    assert entries[0] == {
        "ts": entries[0]["ts"],
        "actorId": "u4",
        "action": "ACCESS_DENIED",
        "resource": "/courses/c1/grades/u4",
        "result": "FORBIDDEN",
    }
    assert entries[1]["actorId"] == "u2"
    assert entries[1]["action"] == "UPDATE_GRADE"
    assert entries[1]["resource"] == "/courses/c1/grades/u4"
    assert entries[1]["result"] == "OK"
    assert entries[1]["oldScore"] == 7.5
    assert entries[1]["newScore"] == 9
    audit_text = "\n".join(lines).lower()
    assert "lms@2026" not in audit_text
    assert student_token.lower() not in audit_text
    assert instructor_token.lower() not in audit_text


def test_default_flask_404_and_405_are_json(client):
    token = login(client, "chi.sv@lms.test")
    headers = auth(token)
    missing = client.get("/no-such-route", headers=headers)
    wrong_method = client.get("/auth/login", headers=headers)
    assert missing.status_code == 404
    assert missing.get_json() == {"error": "NOT_FOUND"}
    assert wrong_method.status_code == 405
    assert wrong_method.get_json() == {"error": "METHOD_NOT_ALLOWED"}


def test_http_exception_403_is_audited_once(app):
    app.add_url_rule(
        "/explicit-forbidden",
        endpoint="explicit_forbidden",
        view_func=lambda: abort(403),
        methods=["GET"],
    )
    token = login(app.test_client(), "chi.sv@lms.test")
    response = app.test_client().get(
        "/explicit-forbidden", headers=auth(token)
    )
    assert response.status_code == 403
    audit_path = app.extensions["lms_store"]["audit_log_path"]
    with open(audit_path, encoding="utf-8") as audit_file:
        lines = audit_file.read().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["action"] == "ACCESS_DENIED"
    assert json.loads(lines[0])["result"] == "FORBIDDEN"


def test_score_validation_is_repeated_inside_service(app):
    instructor = {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"}
    with using_store(app.extensions["lms_store"]):
        with pytest.raises(ValidationError):
            update_grade(instructor, "c1", "u4", float("nan"))


def test_config_dict_overrides_environment(app, tmp_path):
    assert app.config["JWT_SECRET"] == SECRET
    assert app.config["TOKEN_TTL_SECONDS"] == 900
    assert app.config["AUDIT_LOG_PATH"] == str(tmp_path / "audit.log")


def test_create_app_loads_independent_seed_state(tmp_path):
    config = {
        "TESTING": True,
        "JWT_SECRET": SECRET,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
    }
    first = create_app(config)
    second = create_app(config)
    first_store = first.extensions["lms_store"]
    second_store = second.extensions["lms_store"]
    assert first_store is not second_store
    assert store_module.db is second_store
    assert all(
        set(user) == {"id", "email", "role", "pw_hash"}
        and user["pw_hash"].startswith(b"$2b$10$")
        for user in first_store["users"].values()
    )
    first_store["enrollments"][("c1", "u4")] = 1
    assert second_store["enrollments"][("c1", "u4")] == 7.5
