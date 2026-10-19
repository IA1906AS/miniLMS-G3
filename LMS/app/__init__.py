import os
from collections.abc import Mapping
from typing import Any

from flask import Flask, g, jsonify, request

from . import audit, auth, errors, gate, schemas, services, store
from .guards import require_role


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    settings: dict[str, Any] = {
        "JWT_SECRET": os.environ.get("JWT_SECRET"),
        "TOKEN_TTL_SECONDS": os.environ.get("TOKEN_TTL_SECONDS", "900"),
        "AUDIT_LOG_PATH": os.environ.get("AUDIT_LOG_PATH", "audit.log"),
    }
    if config is not None:
        settings.update(config)

    secret = settings.get("JWT_SECRET")
    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be configured with at least 32 characters")

    try:
        token_ttl = int(settings["TOKEN_TTL_SECONDS"])
    except (TypeError, ValueError) as error:
        raise RuntimeError("TOKEN_TTL_SECONDS must be a positive integer") from error
    if token_ttl <= 0:
        raise RuntimeError("TOKEN_TTL_SECONDS must be a positive integer")

    app = Flask(__name__)
    app.config.update(settings)
    app.config["TOKEN_TTL_SECONDS"] = token_ttl

    state = store.init()
    state["audit_log_path"] = app.config["AUDIT_LOG_PATH"]
    app.extensions["lms_store"] = state
    audit.configure(app.config["AUDIT_LOG_PATH"])

    errors.register(app)
    gate.install(app)

    @app.post("/auth/login")
    def login() -> Any:
        email, password = schemas.parse_login_body(request.get_json(silent=True))
        result = auth.login(
            email,
            password,
            app.config["JWT_SECRET"],
            app.config["TOKEN_TTL_SECONDS"],
            state,
        )
        return jsonify(result)

    @app.get("/me")
    def me() -> Any:
        return jsonify(g.actor)

    @app.get("/courses/<course_id>/grades")
    @require_role("ADMIN", "INSTRUCTOR", "STUDENT")
    def course_grades(course_id: str) -> Any:
        with services.using_store(state):
            return jsonify(services.get_grades(g.actor, course_id))

    def perform_grade_update(course_id: str, student_id: str) -> Any:
        with services.using_store(state):
            services.authorize_update(g.actor, course_id)
            score = schemas.validate_grade_body(request.get_json(silent=True))
            return jsonify(
                services.update_grade(g.actor, course_id, student_id, score)
            )

    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("INSTRUCTOR")
    def put_grade(course_id: str, student_id: str) -> Any:
        return perform_grade_update(course_id, student_id)

    return app
