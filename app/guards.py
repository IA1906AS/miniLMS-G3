"""Layer 3 - role guard, applied per route."""
from functools import wraps

from flask import g

from . import services
from .errors import Forbidden, Unauthenticated


def require_role(*roles):
    allowed = frozenset(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            actor = getattr(g, "actor", None)
            if actor is None:  # fail closed
                raise Unauthenticated()
            if actor.get("role") not in allowed:
                raise Forbidden()
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_course(view):
    """404 for an unknown course. Placed outside @require_role so the
    check order stays 401 -> 404 (course) -> 403 -> 400 -> 404 (enrollment)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        services.get_course(kwargs.get("course_id"))
        return view(*args, **kwargs)

    return wrapper
