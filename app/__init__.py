import os
import smtplib
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, request, session

from . import audit, auth, errors, gate, passwords, schemas, services, store, web
from .guards import require_role
from .errors import MailDeliveryFailed, ValidationError


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    settings: dict[str, Any] = {
        "JWT_SECRET": os.environ.get("JWT_SECRET"),
        "TOKEN_TTL_SECONDS": os.environ.get("TOKEN_TTL_SECONDS", "900"),
        "AUDIT_LOG_PATH": os.environ.get("AUDIT_LOG_PATH", "audit.log"),
        "DATABASE_PATH": os.environ.get("DATABASE_PATH", "lms.sqlite3"),
        "PUBLIC_BASE_URL": os.environ.get(
            "PUBLIC_BASE_URL", "http://localhost:5000"
        ),
        "SMTP_HOST": os.environ.get("SMTP_HOST"),
        "SMTP_PORT": os.environ.get("SMTP_PORT", "587"),
        "SMTP_USERNAME": os.environ.get("SMTP_USERNAME"),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD"),
        "SMTP_FROM": os.environ.get("SMTP_FROM"),
        "SMTP_USE_TLS": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
        "SMTP_USE_SSL": os.environ.get("SMTP_USE_SSL", "false").lower() == "true",
        "SESSION_COOKIE_SECURE": os.environ.get(
            "SESSION_COOKIE_SECURE", "false"
        ).lower()
        == "true",
        "GOOGLE_CLIENT_ID": os.environ.get("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "GITHUB_CLIENT_ID": os.environ.get("GITHUB_CLIENT_ID"),
        "GITHUB_CLIENT_SECRET": os.environ.get("GITHUB_CLIENT_SECRET"),
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
    public_base_url = settings["PUBLIC_BASE_URL"]
    if not isinstance(public_base_url, str):
        raise RuntimeError("PUBLIC_BASE_URL must be an HTTP(S) origin")
    parsed_base_url = urlsplit(public_base_url)
    if (
        parsed_base_url.scheme not in {"http", "https"}
        or not parsed_base_url.netloc
        or not parsed_base_url.hostname
        or parsed_base_url.username
        or parsed_base_url.password
        or parsed_base_url.path not in ("", "/")
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        raise RuntimeError("PUBLIC_BASE_URL must be an HTTP(S) origin")

    app = Flask(__name__)
    app.config.update(settings)
    app.config["TOKEN_TTL_SECONDS"] = token_ttl
    app.config["PUBLIC_BASE_URL"] = public_base_url.rstrip("/")
    if app.config.get("TESTING") and "DATABASE_PATH" not in (config or {}):
        app.config["DATABASE_PATH"] = ":memory:"
    app.secret_key = secret
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    state = store.init(app.config["DATABASE_PATH"])
    state["audit_log_path"] = app.config["AUDIT_LOG_PATH"]
    app.extensions["lms_store"] = state
    audit.configure(app.config["AUDIT_LOG_PATH"])

    errors.register(app)
    gate.install(app)
    app.register_blueprint(web.web)

    @app.post("/auth/login")
    def login() -> Any:
        body = request.get_json(silent=True)
        email, password = schemas.parse_login_body(body)
        csrf_token = session.get("csrf_token")
        if csrf_token:
            user = auth.authenticate(email, password, state)
            session.clear()
            session["csrf_token"] = csrf_token
            session["user_id"] = user["id"]
            session.permanent = bool(body.get("remember")) if isinstance(body, dict) else False
            return jsonify(message="Signed in")

        result = auth.login(
            email,
            password,
            app.config["JWT_SECRET"],
            app.config["TOKEN_TTL_SECONDS"],
            state,
        )
        return jsonify(result)

    @app.post("/auth/register")
    def register() -> Any:
        email, name, password = schemas.parse_register_body(
            request.get_json(silent=True)
        )
        result = auth.register(
            email,
            name,
            password,
            app.config["JWT_SECRET"],
            app.config["TOKEN_TTL_SECONDS"],
            state,
        )
        if session.get("csrf_token"):
            return jsonify(message="Account created", user=result["user"]), 201
        return jsonify(result), 201

    @app.post("/auth/password-reset")
    @app.post("/auth/forgot-password")
    def request_password_reset() -> Any:
        email = schemas.parse_password_reset_request(request.get_json(silent=True))
        try:
            passwords.request_password_reset(email, state, app.config)
        except (RuntimeError, OSError, smtplib.SMTPException) as error:
            raise MailDeliveryFailed() from error
        return jsonify(
            message="If the account exists, password reset instructions will be sent."
        ), 202

    @app.post("/auth/password-reset/confirm")
    @app.post("/auth/reset-password")
    def confirm_password_reset() -> Any:
        token, password = schemas.parse_password_reset_confirmation(
            request.get_json(silent=True)
        )
        if not passwords.reset_password(token, password, state):
            raise ValidationError()
        return jsonify(message="Password updated")

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
