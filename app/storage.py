"""Quản lý lưu trữ tệp an toàn (Storage).

Chống path traversal, kiểm tra định dạng và dung lượng tệp.
Không import Flask request trực tiếp; nhận file object hoặc bytes.
"""

import os
import uuid
from typing import Any

from .errors import AppError, ValidationError

# Giới hạn kích thước tệp
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2MB
MAX_MATERIAL_BYTES = 20 * 1024 * 1024  # 20MB
MAX_SUBMISSION_BYTES = 20 * 1024 * 1024  # 20MB

ALLOWED_AVATAR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ALLOWED_MATERIAL_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".txt",
    ".zip",
    ".rar",
    ".xlsx",
    ".csv",
}
ALLOWED_SUBMISSION_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".doc",
    ".txt",
    ".zip",
    ".rar",
    ".py",
    ".java",
    ".c",
    ".cpp",
}


def sanitize_filename(filename: str) -> str:
    """Loại bỏ ký tự nguy hiểm, giữ lại tên cơ bản."""
    base = os.path.basename(filename.strip().replace("\\", "/"))
    return "".join(c for c in base if c.isalnum() or c in "._- ")[:100] or "file"


def secure_save_file(
    file_bytes: bytes,
    original_name: str,
    target_dir: str,
    *,
    allowed_extensions: set[str] | None = None,
    max_bytes: int = MAX_MATERIAL_BYTES,
) -> tuple[str, str, int]:
    """Lưu tệp an toàn vào thư mục chỉ định, trả về (relative_filename, sanitized_name, size)."""
    if len(file_bytes) > max_bytes or len(file_bytes) == 0:
        raise ValidationError()

    clean_name = sanitize_filename(original_name)
    ext = os.path.splitext(clean_name)[1].lower()
    if allowed_extensions is not None and ext not in allowed_extensions:
        raise ValidationError()

    os.makedirs(target_dir, exist_ok=True)
    unique_name = f"{uuid.uuid4().hex}{ext}"
    destination = os.path.abspath(os.path.join(target_dir, unique_name))

    # Đảm bảo không thoát khỏi target_dir
    abs_target = os.path.abspath(target_dir)
    if not destination.startswith(abs_target):
        raise ValidationError()

    with open(destination, "wb") as f:
        f.write(file_bytes)

    return unique_name, clean_name, len(file_bytes)


def resolve_file_path(target_dir: str, filename: str) -> str | None:
    """Lấy đường dẫn an toàn tới tệp, trả về None nếu file không tồn tại hoặc traversal."""
    clean_name = os.path.basename(filename.replace("\\", "/"))
    destination = os.path.abspath(os.path.join(target_dir, clean_name))
    abs_target = os.path.abspath(target_dir)
    if not destination.startswith(abs_target):
        return None
    if not os.path.isfile(destination):
        return None
    return destination

