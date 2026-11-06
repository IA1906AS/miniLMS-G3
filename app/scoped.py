"""Decorator dùng chung cho route: mở scope store trong suốt request."""

from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import current_app

from .runtime import using_store

View = TypeVar("View", bound=Callable[..., Any])


def store_scope(view: View) -> View:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        with using_store(current_app.extensions["lms_store"]):
            return view(*args, **kwargs)

    return cast(View, wrapped)
