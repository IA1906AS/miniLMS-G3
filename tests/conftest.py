"""Cấu hình chung cho test: dùng PostgreSQL thay cho SQLite.

Mỗi test chạy trên cùng một database (mặc định lms_test) nhưng schema `public`
được xoá và tạo lại trước mỗi test để bảo đảm độc lập.
"""

import os

import psycopg
import pytest

DEFAULT_TEST_DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:2010/lms_test"
TEST_DATABASE_URL = os.environ.setdefault("TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
# Test luôn dùng database test, kể cả khi app đọc biến DATABASE_URL mặc định.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


def _ensure_database() -> None:
    """Tạo database test nếu chưa có (dùng quyền của user trong DSN)."""
    base_url, database = TEST_DATABASE_URL.rsplit("/", 1)
    database = database.split("?")[0]
    admin_url = base_url + "/postgres"
    with psycopg.connect(admin_url, autocommit=True) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if not exists:
            connection.execute(f'CREATE DATABASE "{database}"')


_ensure_database()


def _close_stale_connections() -> None:
    """Đóng các kết nối còn mở từ test trước để không cạn max_connections."""
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid()"
        )


@pytest.fixture(autouse=True)
def _reset_database():
    _close_stale_connections()
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS public CASCADE")
        connection.execute("CREATE SCHEMA public")
    yield
    _close_stale_connections()
