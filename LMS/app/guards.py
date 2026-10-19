from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import current_app, g

from app.errors import Forbidden, NotFound, Unauthenticated


View = TypeVar("View", bound=Callable[..., Any])


def require_role(*roles: str) -> Callable[[View], View]:
    allowed_roles = frozenset(roles)

    def decorate(view: View) -> View:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            actor = g.get("actor")
            if actor is None:
                raise Unauthenticated()
            if actor["role"] not in allowed_roles:
                course_id = kwargs.get("course_id")
                if course_id is not None:
                    store = current_app.extensions["lms_store"]
                    if course_id not in store["courses"]:
                        raise NotFound()
                raise Forbidden()
            return view(*args, **kwargs)

        return cast(View, wrapped)

    return decorate
