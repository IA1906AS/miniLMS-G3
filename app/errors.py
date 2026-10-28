from typing import Any

from flask import Flask, g, jsonify, request
from werkzeug.exceptions import HTTPException

from app import audit


class AppError(Exception):
    status, code = 500, "INTERNAL_ERROR"


class Forbidden(AppError):
    status, code = 403, "FORBIDDEN"


class NotFound(AppError):
    status, code = 404, "NOT_FOUND"


class ValidationError(AppError):
    status, code = 400, "VALIDATION_ERROR"


class Unauthenticated(AppError):
    status, code = 401, "UNAUTHENTICATED"


class InvalidCredentials(AppError):
    status, code = 401, "INVALID_CREDENTIALS"


class AccountLocked(AppError):
    status, code = 429, "ACCOUNT_LOCKED"


class Conflict(AppError):
    status, code = 409, "CONFLICT"


class MailDeliveryFailed(AppError):
    status, code = 503, "MAIL_DELIVERY_FAILED"


def register(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(error: AppError) -> tuple[Any, int]:
        if error.status == 403:
            audit.record(
                g.get("actor", {}).get("id"),
                "ACCESS_DENIED",
                request.path,
                "FORBIDDEN",
                path=app.config["AUDIT_LOG_PATH"],
            )
        return jsonify(error=error.code), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error: HTTPException) -> tuple[Any, int]:
        if error.code == 403:
            return handle_app_error(Forbidden())
        code = {
            400: "VALIDATION_ERROR",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
        }.get(error.code, "INTERNAL_ERROR")
        return jsonify(error=code), error.code or 500

    @app.errorhandler(Exception)
    def handle_unexpected_error(error: Exception) -> tuple[Any, int]:
        return jsonify({"error": "INTERNAL_ERROR"}), 500
