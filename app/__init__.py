import os

from flask import Flask, current_app, g, jsonify, request

from . import audit, auth, errors, gate, guards, schemas, services, store

ALL_ROLES = ("ADMIN", "INSTRUCTOR", "STUDENT")


def _build_config(config):
    """Explicit config overrides environment variables."""
    config = dict(config or {})
    cfg = dict(config)
    cfg["JWT_SECRET"] = config.get("JWT_SECRET", os.environ.get("JWT_SECRET"))
    cfg["TOKEN_TTL_SECONDS"] = config.get(
        "TOKEN_TTL_SECONDS", os.environ.get("TOKEN_TTL_SECONDS", 900)
    )
    cfg["AUDIT_LOG_PATH"] = config.get(
        "AUDIT_LOG_PATH", os.environ.get("AUDIT_LOG_PATH", "audit.log")
    )
    cfg["SEED_PATH"] = config.get("SEED_PATH", os.environ.get("SEED_PATH"))

    secret = cfg["JWT_SECRET"]
    if not isinstance(secret, str) or len(secret) < 32 or secret.isspace():
        raise RuntimeError("JWT_SECRET is required and must be at least 32 characters")
    try:
        ttl = cfg["TOKEN_TTL_SECONDS"]
        if isinstance(ttl, bool):
            raise ValueError
        ttl = int(ttl)
        if ttl <= 0:
            raise ValueError
        cfg["TOKEN_TTL_SECONDS"] = ttl
    except (TypeError, ValueError):
        raise RuntimeError("TOKEN_TTL_SECONDS must be a positive integer")
    return cfg


def create_app(config=None):
    cfg = _build_config(config)  # fail closed: no app without a valid secret

    app = Flask(__name__)
    app.config.update(cfg)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.json.sort_keys = False

    state = store.load(cfg["SEED_PATH"])  # fresh state on every call
    logger = audit.AuditLogger(cfg["AUDIT_LOG_PATH"])
    app.extensions["lms_store"] = state
    app.extensions["lms_audit"] = logger
    store.set_current(state)
    audit.configure(logger)

    @app.before_request
    def _bind_state():  # keep module-level state pointing at THIS app's state
        store.set_current(current_app.extensions["lms_store"])
        audit.configure(current_app.extensions["lms_audit"])

    gate.init_gate(app)  # layer 2 (registered after bind, before any route runs)
    errors.register_error_handlers(app)  # layer 6

    @app.after_request
    def _headers(resp):
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    def _body():
        return request.get_json(force=True, silent=True)

    @app.post("/auth/login", endpoint="login")
    def login():
        email, password = schemas.validate_login_body(_body())
        ttl = app.config["TOKEN_TTL_SECONDS"]
        token = auth.login(
            store.current(), email, password, app.config["JWT_SECRET"], ttl
        )
        return jsonify({"accessToken": token, "expiresIn": ttl})

    @app.get("/me", endpoint="me")
    @guards.require_role(*ALL_ROLES)
    def me():
        a = g.actor
        return jsonify({"id": a["id"], "email": a["email"], "role": a["role"]})

    @app.get("/courses/<course_id>/grades", endpoint="get_grades")
    @guards.require_course
    @guards.require_role(*ALL_ROLES)
    def get_grades(course_id):
        return jsonify(services.get_grades(g.actor, course_id))

    @app.put("/courses/<course_id>/grades/<student_id>", endpoint="update_grade")
    @guards.require_course
    @guards.require_role("INSTRUCTOR")
    def update_grade(course_id, student_id):
        services.authorize_update_grade(g.actor, course_id)  # 403 before 400
        score = schemas.validate_grade_body(_body())  # 400
        result = services.update_grade(g.actor, course_id, student_id, score)  # 404
        return jsonify(result)

    return app
