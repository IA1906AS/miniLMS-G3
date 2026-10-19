"""Layer 6 - output & fail-closed: every error is JSON {"error": CODE}, no stack traces."""
import logging

from flask import g, jsonify, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger("lms")


class AppError(Exception):
    status = 500
    code = "INTERNAL_ERROR"


class ValidationError(AppError):
    status = 400
    code = "VALIDATION_ERROR"


class InvalidCredentials(AppError):
    status = 401
    code = "INVALID_CREDENTIALS"


class Unauthenticated(AppError):
    status = 401
    code = "UNAUTHENTICATED"


class Forbidden(AppError):
    status = 403
    code = "FORBIDDEN"


class NotFound(AppError):
    status = 404
    code = "NOT_FOUND"


class AccountLocked(AppError):
    status = 429
    code = "ACCOUNT_LOCKED"

    def __init__(self, retry_after=None):
        super().__init__()
        self.retry_after = retry_after


_HTTP_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    413: "PAYLOAD_TOO_LARGE",
    415: "VALIDATION_ERROR",
    429: "ACCOUNT_LOCKED",
}


def _json_error(code, status, headers=None):
    resp = jsonify({"error": code})
    resp.status_code = status
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp


def _audit_forbidden():
    """Layer 8: every 403 produces one audit line."""
    from . import audit  # local import keeps module graph simple

    actor = getattr(g, "actor", None)
    endpoint = request.endpoint or "unknown"
    action = {
        "update_grade": "UPDATE_GRADE",
        "get_grades": "READ_GRADES",
    }.get(endpoint, f"{request.method} {endpoint}")
    audit.get().log(
        actor_id=actor["id"] if actor else None,
        action=action,
        resource=request.path,
        result="DENIED",
    )


def register_error_handlers(app):
    @app.errorhandler(AppError)
    def _app_error(exc):
        if isinstance(exc, Forbidden):
            _audit_forbidden()
        headers = {}
        if isinstance(exc, AccountLocked) and exc.retry_after:
            headers["Retry-After"] = str(int(exc.retry_after))
        return _json_error(exc.code, exc.status, headers)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        status = exc.code or 500
        code = _HTTP_CODES.get(status)
        if code is None:
            code = "INTERNAL_ERROR" if status >= 500 else "BAD_REQUEST"
        if status == 403:
            _audit_forbidden()
        return _json_error(code, status)

    @app.errorhandler(Exception)
    def _unexpected(exc):
        log.exception("unhandled error")  # stack trace goes to server log only
        return _json_error("INTERNAL_ERROR", 500)
