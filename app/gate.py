"""Layer 2 - deny by default. Every request needs a valid token except the allowlist."""
from flask import g, request

from . import auth, store
from .errors import Unauthenticated

ALLOWLIST = frozenset({("POST", "/auth/login")})  # the only public endpoint


def _bearer_token():
    header = request.headers.get("Authorization", "")
    parts = header.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise Unauthenticated()
    return parts[1]


def init_gate(app):
    @app.before_request
    def default_deny():
        if (request.method, request.path) in ALLOWLIST:
            return None
        g.actor = auth.authenticate(
            _bearer_token(), app.config["JWT_SECRET"], store.current()
        )
        return None
