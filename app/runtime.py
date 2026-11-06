"""Truy cập store đang hoạt động mà không cần Flask.

`create_app()` gắn store vào `app.extensions`; mỗi request mở một scope bằng
`using_store(...)` để service lấy đúng state thay vì biến global.
"""

import contextlib
import contextvars
from collections.abc import Iterator
from typing import Any

_active_store: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "lms_store_context", default=None
)


@contextlib.contextmanager
def using_store(store: dict[str, Any]) -> Iterator[None]:
    token = _active_store.set(store)
    try:
        yield
    finally:
        _active_store.reset(token)


def current_store() -> dict[str, Any]:
    store = _active_store.get()
    if store is None:
        from . import store as store_module

        store = store_module.db
    if store is None:
        raise RuntimeError("The LMS store has not been initialized")
    return store
