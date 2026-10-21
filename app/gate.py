import hmac

from flask import Flask, g, request, session

from . import auth, store
from .errors import Unauthenticated, ValidationError


ALLOWLIST = {
    ("POST", "/auth/login"),
    ("POST", "/auth/register"),
    ("POST", "/auth/password-reset"),
    ("POST", "/auth/password-reset/confirm"),
    ("POST", "/auth/forgot-password"),
    ("POST", "/auth/reset-password"),
}


def install(app: Flask) -> None:
    @app.before_request
    def _gate() -> None:
        if request.endpoint == "static":
            return
        state = app.extensions["lms_store"]
        store.refresh(state)
        if request.endpoint is not None and request.endpoint.startswith("web."):
            return
        if (request.method, request.path) in ALLOWLIST:
            expected = session.get("csrf_token")
            if expected is not None:
                supplied = request.headers.get("X-CSRF-Token", "")
                if (
                    not isinstance(expected, str)
                    or not supplied
                    or not hmac.compare_digest(expected, supplied)
                ):
                    raise ValidationError()
            return

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            raise Unauthenticated()

        g.actor = auth.verify_token(
            authorization[7:].strip(),
            app.config["JWT_SECRET"],
            state,
        )


install_gate = install
