import base64
import json
import time

import pytest

from app import auth, create_app, guards, services
from app.errors import Forbidden, ValidationError

PW = "Lms@2026"
SECRET = "unit-test-secret-0123456789-abcdefghij"


@pytest.fixture
def audit_path(tmp_path):
    return tmp_path / "audit.log"


@pytest.fixture
def app(audit_path):
    return create_app({"JWT_SECRET": SECRET, "AUDIT_LOG_PATH": str(audit_path)})


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email, pw=PW):
    return client.post("/auth/login", json={"email": email, "password": pw})


def hdr(client, email):
    tok = login(client, email).get_json()["accessToken"]
    return {"Authorization": f"Bearer {tok}"}


def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def unb64(s):
    return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))


# ---- layer 1 ----
def test_a1_login_failures_identical(client):
    r1 = login(client, "khongco@lms.test")
    r2 = login(client, "chi.sv@lms.test", "wrong")
    assert r1.status_code == r2.status_code == 401
    assert r1.get_data() == r2.get_data()
    assert r1.get_json() == {"error": "INVALID_CREDENTIALS"}


def test_login_success_shape(client):
    r = login(client, "chi.sv@lms.test")
    assert r.status_code == 200
    assert set(r.get_json()) == {"accessToken", "expiresIn"}
    assert r.get_json()["expiresIn"] == 900


def test_token_has_only_sub_iat_exp(client):
    tok = login(client, "chi.sv@lms.test").get_json()["accessToken"]
    assert set(unb64(tok.split(".")[1])) == {"sub", "iat", "exp"}


def test_a3_tampered_sub(client):
    tok = login(client, "chi.sv@lms.test").get_json()["accessToken"]
    h, p, s = tok.split(".")
    payload = unb64(p)
    payload["sub"] = "u1"
    forged = f"{h}.{b64(payload)}.{s}"
    r = client.get("/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401 and r.get_json() == {"error": "UNAUTHENTICATED"}


def test_a4_alg_none(client):
    now = int(time.time())
    tok = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': 'u1', 'iat': now, 'exp': now + 900})}."
    r = client.get("/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_a5_expired(audit_path):
    app = create_app(
        {"JWT_SECRET": SECRET, "AUDIT_LOG_PATH": str(audit_path), "TOKEN_TTL_SECONDS": 1}
    )
    c = app.test_client()
    h = hdr(c, "chi.sv@lms.test")
    assert c.get("/me", headers=h).status_code == 200
    time.sleep(2)
    assert c.get("/me", headers=h).status_code == 401


# ---- layer 2 ----
def test_a2_me_no_token(client):
    r = client.get("/me")
    assert r.status_code == 401 and r.get_json() == {"error": "UNAUTHENTICATED"}


def test_a16_undeclared_route_protected(app):
    app.add_url_rule("/debug", "debug", lambda: "secret")
    c = app.test_client()
    assert c.get("/debug").status_code == 401
    assert c.get("/does-not-exist").status_code == 401


def test_missing_user_in_token(app):
    c = app.test_client()
    h = hdr(c, "chi.sv@lms.test")
    del app.extensions["lms_store"].users["u4"]
    assert c.get("/me", headers=h).status_code == 401


# ---- layer 6 ----
def test_a6_no_password_leak(client):
    bodies = [
        login(client, "chi.sv@lms.test").get_data(as_text=True),
        login(client, "x@x", "bad").get_data(as_text=True),
    ]
    h = hdr(client, "an.gv@lms.test")
    for path in ("/me", "/courses/c1/grades", "/courses/c2/grades", "/nope"):
        bodies.append(client.get(path, headers=h).get_data(as_text=True))
    for b in bodies:
        low = b.lower()
        assert "password" not in low and "passwordhash" not in low


def test_a17_missing_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        create_app()
    with pytest.raises(RuntimeError):
        create_app({"JWT_SECRET": "short"})


def test_env_secret_and_config_override(monkeypatch, audit_path):
    monkeypatch.setenv("JWT_SECRET", "e" * 40)
    monkeypatch.setenv("TOKEN_TTL_SECONDS", "123")
    app = create_app({"AUDIT_LOG_PATH": str(audit_path)})
    assert app.config["TOKEN_TTL_SECONDS"] == 123
    app2 = create_app({"AUDIT_LOG_PATH": str(audit_path), "TOKEN_TTL_SECONDS": 5})
    assert app2.config["TOKEN_TTL_SECONDS"] == 5


def test_json_errors_404_405_500(app):
    def boom():
        raise Exception("secret internals")

    app.add_url_rule("/boom", "boom", boom)
    c = app.test_client()
    h = hdr(c, "an.gv@lms.test")
    r = c.get("/nope", headers=h)
    assert r.status_code == 404 and r.get_json() == {"error": "NOT_FOUND"}
    r = c.delete("/me", headers=h)
    assert r.status_code == 405 and "error" in r.get_json()
    r = c.get("/boom", headers=h)
    assert r.status_code == 500 and r.get_json() == {"error": "INTERNAL_ERROR"}
    assert "secret internals" not in r.get_data(as_text=True)


def test_fresh_state_per_create_app(audit_path):
    a = create_app({"JWT_SECRET": SECRET, "AUDIT_LOG_PATH": str(audit_path)})
    c = a.test_client()
    h = hdr(c, "an.gv@lms.test")
    assert c.put("/courses/c1/grades/u4", json={"score": 1}, headers=h).status_code == 200
    b = create_app({"JWT_SECRET": SECRET, "AUDIT_LOG_PATH": str(audit_path)})
    c2 = b.test_client()
    h2 = hdr(c2, "chi.sv@lms.test")
    assert c2.get("/courses/c1/grades", headers=h2).get_json()[0]["score"] == 7.5


# ---- layers 3/4 ----
def test_a7_a8(client):
    h = hdr(client, "chi.sv@lms.test")
    r = client.get("/courses/c1/grades", headers=h)
    assert r.status_code == 200 and r.get_json() == [{"studentId": "u4", "score": 7.5}]
    assert client.get("/courses/c2/grades", headers=h).status_code == 403


def test_get_matrix(client):
    assert len(client.get("/courses/c1/grades", headers=hdr(client, "admin@lms.test")).get_json()) == 2
    assert len(client.get("/courses/c1/grades", headers=hdr(client, "an.gv@lms.test")).get_json()) == 2
    assert client.get("/courses/c1/grades", headers=hdr(client, "binh.gv@lms.test")).status_code == 403
    assert client.get("/courses/c1/grades", headers=hdr(client, "em.sv@lms.test")).status_code == 403


def test_a9_a10_a11(client):
    for email in ("chi.sv@lms.test", "binh.gv@lms.test", "admin@lms.test"):
        r = client.put("/courses/c1/grades/u4", json={"score": 10}, headers=hdr(client, email))
        assert r.status_code == 403 and r.get_json() == {"error": "FORBIDDEN"}


# ---- layer 5 ----
@pytest.mark.parametrize(
    "body",
    [{"score": 11}, {"score": -1}, {"score": "10"}, {"score": True}, {"score": 9, "courseId": "c2"}],
)
def test_a12_validation(client, body):
    r = client.put("/courses/c1/grades/u4", json=body, headers=hdr(client, "an.gv@lms.test"))
    assert r.status_code == 400 and r.get_json() == {"error": "VALIDATION_ERROR"}


def test_validation_misc(client):
    h = hdr(client, "an.gv@lms.test")
    for raw in (b"not json", b"[]", b"null", b'{"score": NaN}', b"{}"):
        r = client.put("/courses/c1/grades/u4", data=raw, headers=h)
        assert r.status_code == 400
    assert client.put("/courses/c1/grades/u4", json={"score": 0}, headers=h).status_code == 200
    assert client.put("/courses/c1/grades/u4", json={"score": 10}, headers=h).status_code == 200


def test_a13_not_enrolled(client):
    r = client.put("/courses/c1/grades/u6", json={"score": 5}, headers=hdr(client, "an.gv@lms.test"))
    assert r.status_code == 404 and r.get_json() == {"error": "NOT_FOUND"}


def test_a14_update_visible(client):
    r = client.put("/courses/c1/grades/u4", json={"score": 9}, headers=hdr(client, "an.gv@lms.test"))
    assert r.status_code == 200
    assert r.get_json() == {"courseId": "c1", "studentId": "u4", "score": 9}
    r = client.get("/courses/c1/grades", headers=hdr(client, "chi.sv@lms.test"))
    assert r.get_json() == [{"studentId": "u4", "score": 9}]


def test_check_order(client):
    chi = hdr(client, "chi.sv@lms.test")
    an = hdr(client, "an.gv@lms.test")
    binh = hdr(client, "binh.gv@lms.test")
    assert client.get("/courses/c9/grades").status_code == 401  # 401 first
    assert client.get("/courses/c9/grades", headers=chi).status_code == 404  # 404 course
    assert client.put("/courses/c9/grades/u4", json={"score": 1}, headers=chi).status_code == 404
    assert client.put("/courses/c1/grades/u4", json={"score": 99}, headers=binh).status_code == 403  # 403 before 400
    assert client.put("/courses/c1/grades/u6", json={"score": 99}, headers=an).status_code == 400  # 400 before 404
    assert client.put("/courses/c1/grades/u6", json={"score": 5}, headers=an).status_code == 404


def test_a15_without_require_role(monkeypatch, audit_path):
    monkeypatch.setattr(guards, "require_role", lambda *roles: (lambda f: f))
    app = create_app({"JWT_SECRET": SECRET, "AUDIT_LOG_PATH": str(audit_path)})
    c = app.test_client()
    for email in ("chi.sv@lms.test", "binh.gv@lms.test", "admin@lms.test"):
        r = c.put("/courses/c1/grades/u4", json={"score": 10}, headers=hdr(c, email))
        assert r.status_code == 403
    chi = {"id": "u4", "email": "chi.sv@lms.test", "role": "STUDENT"}
    with pytest.raises(Forbidden):
        services.update_grade(chi, "c1", "u4", 10)
    with pytest.raises(Forbidden):
        services.get_grades(chi, "c2")
    with pytest.raises(Forbidden):
        services.update_grade(None, "c1", "u4", 10)
    an = {"id": "u2", "email": "an.gv@lms.test", "role": "INSTRUCTOR"}
    with pytest.raises(ValidationError):
        services.update_grade(an, "c1", "u4", 11)


# ---- layer 7 ----
def test_a18_lockout(client):
    for _ in range(5):
        assert login(client, "dung.sv@lms.test", "bad").status_code == 401
    r = login(client, "dung.sv@lms.test", PW)
    assert r.status_code == 429 and r.get_json() == {"error": "ACCOUNT_LOCKED"}


def test_lock_reset_and_expiry(client, monkeypatch):
    for _ in range(4):
        login(client, "dung.sv@lms.test", "bad")
    assert login(client, "dung.sv@lms.test", PW).status_code == 200  # reset
    for _ in range(4):
        login(client, "dung.sv@lms.test", "bad")
    assert login(client, "dung.sv@lms.test", PW).status_code == 200
    for _ in range(5):
        login(client, "em.sv@lms.test", "bad")
    assert login(client, "em.sv@lms.test", PW).status_code == 429
    real = auth._clock
    monkeypatch.setattr(auth, "_clock", lambda: real() + 16 * 60)
    assert login(client, "em.sv@lms.test", PW).status_code == 200


# ---- layer 8 ----
def test_a19_audit(client, audit_path):
    client.put("/courses/c1/grades/u4", json={"score": 0}, headers=hdr(client, "binh.gv@lms.test"))
    client.put("/courses/c1/grades/u4", json={"score": 9}, headers=hdr(client, "an.gv@lms.test"))
    raw = audit_path.read_text(encoding="utf-8")
    lines = [json.loads(x) for x in raw.splitlines()]
    assert len(lines) == 2
    for ln in lines:
        assert {"ts", "actorId", "action", "resource", "result"} <= set(ln)
    assert lines[0]["actorId"] == "u3" and lines[0]["result"] == "DENIED"
    assert lines[1]["actorId"] == "u2" and lines[1]["oldScore"] == 7.5 and lines[1]["newScore"] == 9
    assert PW not in raw and "eyJ" not in raw and "password" not in raw.lower()
