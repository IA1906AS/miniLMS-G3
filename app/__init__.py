import os
import smtplib
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import click
from flask import Flask, g, jsonify, request, session

from . import (
    account,
    admin,
    assignments,
    audit,
    auth,
    courses,
    errors,
    forum,
    gate,
    grades_v2,
    materials,
    outbox,
    passwords,
    quizzes,
    schemas,
    services,
    store,
    web,
)
from .errors import MailDeliveryFailed, ValidationError
from .guards import require_role


def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    settings: dict[str, Any] = {
        "JWT_SECRET": os.environ.get("JWT_SECRET"),
        "TOKEN_TTL_SECONDS": os.environ.get("TOKEN_TTL_SECONDS", "900"),
        "AUDIT_LOG_PATH": os.environ.get("AUDIT_LOG_PATH", "audit.log"),
        "DATABASE_PATH": os.environ.get("DATABASE_PATH", "lms.sqlite3"),
        "PUBLIC_BASE_URL": os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000"),
        "SMTP_HOST": os.environ.get("SMTP_HOST"),
        "SMTP_PORT": os.environ.get("SMTP_PORT", "587"),
        "SMTP_USERNAME": os.environ.get("SMTP_USERNAME"),
        "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD"),
        "SMTP_FROM": os.environ.get("SMTP_FROM"),
        "SMTP_USE_TLS": os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
        "SMTP_USE_SSL": os.environ.get("SMTP_USE_SSL", "false").lower() == "true",
        "SESSION_COOKIE_SECURE": os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
        "GOOGLE_CLIENT_ID": os.environ.get("GOOGLE_CLIENT_ID"),
        "GOOGLE_CLIENT_SECRET": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "GITHUB_CLIENT_ID": os.environ.get("GITHUB_CLIENT_ID"),
        "GITHUB_CLIENT_SECRET": os.environ.get("GITHUB_CLIENT_SECRET"),
        "OUTBOX_MAX_ATTEMPTS": os.environ.get("OUTBOX_MAX_ATTEMPTS", "5"),
        "OUTBOX_RETRY_DELAY_SECONDS": os.environ.get("OUTBOX_RETRY_DELAY_SECONDS", "2"),
        "OUTBOX_LEASE_SECONDS": os.environ.get("OUTBOX_LEASE_SECONDS", "60"),
        "OUTBOX_BATCH_SIZE": os.environ.get("OUTBOX_BATCH_SIZE", "10"),
        "OUTBOX_POLL_INTERVAL": os.environ.get("OUTBOX_POLL_INTERVAL", "0"),
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

    clock = app.config.get("CLOCK") or time.time
    state = store.init(app.config["DATABASE_PATH"], clock=clock)
    state["audit_log_path"] = app.config["AUDIT_LOG_PATH"]
    app.extensions["lms_store"] = state
    audit.configure(app.config["AUDIT_LOG_PATH"])

    errors.register(app)
    gate.install(app)
    app.register_blueprint(web.web)
    app.register_blueprint(admin.bp)
    app.register_blueprint(account.bp)
    app.register_blueprint(courses.bp)
    app.register_blueprint(assignments.bp)
    app.register_blueprint(forum.bp)
    app.register_blueprint(grades_v2.bp)
    app.register_blueprint(materials.bp)
    app.register_blueprint(quizzes.bp)

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
        email, name, password = schemas.parse_register_body(request.get_json(silent=True))
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
        token, password = schemas.parse_password_reset_confirmation(request.get_json(silent=True))
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
            return jsonify(services.update_grade(g.actor, course_id, student_id, score))

    @app.put("/courses/<course_id>/grades/<student_id>")
    @require_role("INSTRUCTOR")
    def put_grade(course_id: str, student_id: str) -> Any:
        return perform_grade_update(course_id, student_id)

    @app.post("/me/enrollments")
    @require_role("STUDENT")
    def enroll() -> Any:
        course_id = schemas.parse_self_enrollment_body(request.get_json(silent=True))
        with services.using_store(state):
            return jsonify(services.enroll_in_course(g.actor, course_id)), 201

    @app.get("/api/docs/openapi.yaml")
    def openapi_spec() -> Any:
        spec_path = os.path.abspath(os.path.join(app.root_path, "..", "docs", "openapi.yaml"))
        if not os.path.isfile(spec_path):
            return {"error": "NOT_FOUND"}, 404
        from flask import send_file

        return send_file(spec_path, mimetype="text/yaml")

    @app.cli.group("outbox")
    def outbox_cli() -> None:
        """Inspect and drain the transactional outbox."""

    @outbox_cli.command("drain")
    @click.option("--limit", type=int, default=None, help="Maximum events to send.")
    def outbox_drain(limit: int | None) -> None:
        delivered = outbox.drain_once(state, app.config, limit=limit)
        click.echo(f"delivered={delivered}")

    @outbox_cli.command("status")
    def outbox_status() -> None:
        counts = store.outbox_counts(state)
        if not counts:
            click.echo("outbox is empty")
            return
        for status in sorted(counts):
            click.echo(f"{status}={counts[status]}")

    outbox.start_worker(app)
    return app
