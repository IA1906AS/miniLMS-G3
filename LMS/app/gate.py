from flask import Flask, g, request

from . import auth
from .errors import Unauthenticated


ALLOWLIST = {("POST", "/auth/login")}


def install(app: Flask) -> None:
    @app.before_request
    def _gate() -> None:
        if (request.method, request.path) in ALLOWLIST:
            return
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer ") or not authorization[7:].strip():
            raise Unauthenticated()

        g.actor = auth.verify_token(
            authorization[7:].strip(),
            app.config["JWT_SECRET"],
            app.extensions["lms_store"],
        )


install_gate = install
