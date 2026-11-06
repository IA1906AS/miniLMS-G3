"""Nghiệp vụ tài liệu bài giảng (Materials).

Tải lên, danh sách, tải xuống và xoá tài liệu môn học.
Chỉ giảng viên phụ trách hoặc ADMIN được tạo/xoá; sinh viên đã ghi danh được tải.
"""

import contextlib
import os
from typing import Any

from . import audit, storage
from . import store as store_module
from .errors import Forbidden, NotFound, ValidationError
from .runtime import current_store


def _role(actor: dict[str, Any]) -> str | None:
    return actor.get("role") if isinstance(actor, dict) else None


def _course(state: dict[str, Any], course_id: str) -> dict[str, Any]:
    course = state["courses"].get(course_id)
    if course is None:
        raise NotFound()
    return course


def _can_manage(actor: dict[str, Any], course: dict[str, Any]) -> bool:
    return _role(actor) == "ADMIN" or (
        _role(actor) == "INSTRUCTOR" and course["instructorId"] == actor.get("id")
    )


def authorize_manage(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if not _can_manage(actor, course):
            raise Forbidden()
        return course


def authorize_view(actor: dict[str, Any], course_id: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        course = _course(state, course_id)
        if _can_manage(actor, course):
            return course
        if _role(actor) == "STUDENT" and (course_id, actor.get("id")) in state["enrollments"]:
            return course
        raise Forbidden()


def create_material(
    actor: dict[str, Any],
    course_id: str,
    title: str,
    file_bytes: bytes,
    original_name: str,
    upload_dir: str,
) -> dict[str, Any]:
    if not title or not title.strip() or len(title) > 200:
        raise ValidationError()

    state = current_store()
    with state["lock"]:
        authorize_manage(actor, course_id)
        stored_name, clean_name, file_size = storage.secure_save_file(
            file_bytes,
            original_name,
            upload_dir,
            allowed_extensions=storage.ALLOWED_MATERIAL_EXTENSIONS,
            max_bytes=storage.MAX_MATERIAL_BYTES,
        )
        material = store_module.create_material(
            state,
            course_id=course_id,
            title=title.strip(),
            file_name=clean_name,
            file_path=stored_name,
            file_size=file_size,
            created_by=str(actor.get("id")),
            now=state["now"](),
        )
        audit.record(
            actor["id"],
            "MATERIAL_CREATE",
            f"/courses/{course_id}/materials",
            "OK",
            materialId=material["id"],
            path=state["audit_log_path"],
        )
        return material


def list_materials(actor: dict[str, Any], course_id: str) -> list[dict[str, Any]]:
    state = current_store()
    with state["lock"]:
        authorize_view(actor, course_id)
        return store_module.list_materials(state, course_id)


def get_material_for_download(
    actor: dict[str, Any], material_id: str, upload_dir: str
) -> tuple[str, str]:
    state = current_store()
    with state["lock"]:
        material = store_module.get_material(state, material_id)
        if material is None:
            raise NotFound()
        authorize_view(actor, material["courseId"])
        filepath = storage.resolve_file_path(upload_dir, material["filePath"])
        if not filepath:
            raise NotFound()
        return filepath, material["fileName"]


def delete_material(actor: dict[str, Any], material_id: str, upload_dir: str) -> dict[str, Any]:
    state = current_store()
    with state["lock"]:
        material = store_module.get_material(state, material_id)
        if material is None:
            raise NotFound()
        authorize_manage(actor, material["courseId"])
        deleted = store_module.delete_material(state, material_id)
        if not deleted:
            raise NotFound()
        filepath = storage.resolve_file_path(upload_dir, material["filePath"])
        if filepath and os.path.isfile(filepath):
            with contextlib.suppress(OSError):
                os.remove(filepath)
        audit.record(
            actor["id"],
            "MATERIAL_DELETE",
            f"/materials/{material_id}",
            "OK",
            materialId=material_id,
            path=state["audit_log_path"],
        )
        return {"id": material_id, "deleted": True}
