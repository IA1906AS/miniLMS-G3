import hmac
import os
import secrets
import smtplib
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar, cast

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from . import (
    account_service,
    admin_service,
    assignment_service,
    audit,
    auth,
    course_service,
    forum_service,
    material_service,
    oauth,
    passwords,
    quiz_service,
    schemas,
    services,
    storage,
    store,
)
from .errors import (
    AccountLocked,
    AppError,
    Conflict,
    Forbidden,
    InvalidCredentials,
    NotFound,
    ValidationError,
)

web = Blueprint("web", __name__)
View = TypeVar("View", bound=Callable[..., Any])


@web.before_request
def check_csrf_token() -> None:
    if request.method != "POST":
        return
    submitted = request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    if not submitted or not expected or not hmac.compare_digest(submitted, expected):
        abort(400)


@web.app_context_processor
def current_user_context() -> dict[str, Any]:
    state = current_app.extensions["lms_store"]
    return {"current_user": state["users"].get(session.get("user_id"))}


@web.app_context_processor
def csrf_context() -> dict[str, Callable[[], str]]:
    def get_csrf_token() -> str:
        token = session.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["csrf_token"] = token
        return token

    return {"csrf_token": get_csrf_token}


def login_required(view: View) -> View:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        state = current_app.extensions["lms_store"]
        user = state["users"].get(session.get("user_id"))
        if user is None:
            session.pop("user_id", None)
            return redirect(url_for("web.login_form"))
        g.web_user = user
        return view(*args, **kwargs)

    return cast(View, wrapped)


@web.app_template_filter("dt")
def _format_datetime(value: Any) -> str:
    from datetime import datetime

    try:
        return datetime.fromtimestamp(float(value)).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


@web.get("/")
def home() -> str:
    state = current_app.extensions["lms_store"]
    user = state["users"].get(session.get("user_id"))
    return render_template(
        "home.html",
        user=user,
        courses=list(state["courses"].values()),
    )


@web.route("/login", methods=["GET", "POST"])
def login_form() -> str | Any:
    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")
        try:
            user = auth.authenticate(email, password, current_app.extensions["lms_store"])
        except AccountLocked:
            return render_template(
                "login.html", error="Tài khoản tạm khóa do đăng nhập sai nhiều lần."
            ), 429
        except (InvalidCredentials, ValidationError):
            return render_template("login.html", error="Email hoặc mật khẩu không chính xác."), 401
        session.clear()
        session["user_id"] = user["id"]
        audit.record(
            user["id"],
            "LOGIN",
            "/login",
            "OK",
            path=current_app.extensions["lms_store"]["audit_log_path"],
        )
        return redirect(url_for("web.account"))
    return render_template("login.html")


@web.route("/register", methods=["GET", "POST"])
def register_form() -> str | Any:
    if request.method == "POST":
        body = {
            "email": request.form.get("email", ""),
            "name": request.form.get("name", ""),
            "password": request.form.get("password", ""),
        }
        try:
            if (
                request.form.get("password") != request.form.get("confirm_password")
                or request.form.get("terms") != "on"
            ):
                raise ValidationError()
            email, name, password = schemas.parse_register_body(body)
            auth.register(
                email,
                name,
                password,
                current_app.config["JWT_SECRET"],
                current_app.config["TOKEN_TTL_SECONDS"],
                current_app.extensions["lms_store"],
            )
        except ValidationError:
            return render_template(
                "register.html",
                error="Vui lòng kiểm tra thông tin, xác nhận mật khẩu và các điều kiện bảo mật.",
            ), 400
        except Conflict:
            return render_template("register.html", error="Email này đã được đăng ký."), 409
        return redirect(url_for("web.login_form", registered="1"))
    return render_template("register.html")


@web.get("/account")
@login_required
def account() -> str:
    user = g.web_user
    state = current_app.extensions["lms_store"]
    available: list[dict[str, Any]] = []
    if user["role"] == "STUDENT":
        courses = [
            {
                **state["courses"][course_id],
                "score": score,
            }
            for (course_id, student_id), score in state["enrollments"].items()
            if student_id == user["id"] and course_id in state["courses"]
        ]
        available = [
            course
            for course in state["courses"].values()
            if (course["id"], user["id"]) not in state["enrollments"]
        ]
    elif user["role"] == "INSTRUCTOR":
        courses = [
            course for course in state["courses"].values() if course["instructorId"] == user["id"]
        ]
    else:
        courses = list(state["courses"].values())
    profile = {
        "fullName": user.get("name", ""),
        "bio": state["bios"].get(user["id"], ""),
        "phone": state["phones"].get(user["id"], ""),
    }
    return render_template(
        "account.html",
        user=user,
        courses=courses,
        available=available,
        profile=profile,
        has_avatar=bool(state["avatars"].get(user["id"])),
    )


@web.post("/courses/<course_id>/enroll")
@login_required
def enroll_course(course_id: str) -> Any:
    try:
        with services.using_store(current_app.extensions["lms_store"]):
            services.enroll_in_course(g.web_user, course_id, current_app.config)
    except Conflict:
        flash("Bạn đã đăng ký khóa học này rồi.", "error")
    except Forbidden:
        abort(403)
    except NotFound:
        abort(404)
    else:
        flash(
            "Đăng ký thành công. Email xác nhận sẽ được gửi tới hộp thư của bạn.",
            "info",
        )
    return redirect(url_for("web.account"))


@web.post("/logout")
def logout() -> Any:
    session.clear()
    return redirect(url_for("web.home"))


@web.get("/oauth/<provider>")
def oauth_start(provider: str) -> Any:
    if provider not in oauth.PROVIDERS:
        abort(404)
    state = oauth.new_state()
    verifier = oauth.new_verifier()
    session["oauth_state"] = state
    session["oauth_provider"] = provider
    session["oauth_verifier"] = verifier
    session["oauth_started_at"] = time.time()
    redirect_uri = (
        f"{current_app.config['PUBLIC_BASE_URL']}{url_for('web.oauth_callback', provider=provider)}"
    )
    try:
        authorization_url = oauth.create_authorization_url(
            provider, current_app.config, redirect_uri, state, verifier
        )
    except oauth.OAuthError:
        session.pop("oauth_state", None)
        session.pop("oauth_provider", None)
        session.pop("oauth_verifier", None)
        session.pop("oauth_started_at", None)
        flash(
            f"Đăng nhập {provider.title()} chưa được cấu hình. "
            "Vui lòng dùng email hoặc liên hệ quản trị viên.",
            "error",
        )
        return redirect(url_for("web.login_form"))
    return redirect(authorization_url)


@web.get("/oauth/<provider>/callback")
def oauth_callback(provider: str) -> Any:
    if provider not in oauth.PROVIDERS:
        abort(404)

    expected_state = session.pop("oauth_state", None)
    expected_provider = session.pop("oauth_provider", None)
    verifier = session.pop("oauth_verifier", None)
    started_at = session.pop("oauth_started_at", None)
    received_state = request.args.get("state", "")
    if (
        not isinstance(expected_state, str)
        or not isinstance(verifier, str)
        or expected_provider != provider
        or not isinstance(started_at, (int, float))
        or time.time() - started_at > 600
        or time.time() < started_at
        or not received_state
        or not hmac.compare_digest(expected_state, received_state)
    ):
        flash("Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng thử lại.", "error")
        return redirect(url_for("web.login_form"))
    if request.args.get("error"):
        flash("Bạn đã huỷ đăng nhập hoặc nhà cung cấp từ chối xác thực.", "error")
        return redirect(url_for("web.login_form"))

    code = request.args.get("code", "")
    if not code or len(code) > 2048:
        flash("Không thể xác thực tài khoản. Vui lòng thử lại.", "error")
        return redirect(url_for("web.login_form"))

    redirect_uri = (
        f"{current_app.config['PUBLIC_BASE_URL']}{url_for('web.oauth_callback', provider=provider)}"
    )
    try:
        profile = oauth.fetch_profile(provider, current_app.config, code, redirect_uri, verifier)
        user = store.get_or_create_oauth_user(
            current_app.extensions["lms_store"],
            provider=provider,
            subject=profile["subject"],
            email=profile["email"],
            name=profile["name"],
        )
    except oauth.OAuthEmailConflict:
        flash(
            "Email này đã có tài khoản MiniLMS. Hãy đăng nhập bằng email và mật khẩu hiện tại.",
            "error",
        )
        return redirect(url_for("web.login_form"))
    except oauth.OAuthError:
        flash(
            "Không thể xác thực với nhà cung cấp lúc này. Vui lòng thử lại.",
            "error",
        )
        return redirect(url_for("web.login_form"))
    except ValueError:
        flash(
            "Email này đã có tài khoản MiniLMS. Hãy đăng nhập bằng email và mật khẩu hiện tại.",
            "error",
        )
        return redirect(url_for("web.login_form"))

    session.clear()
    session["csrf_token"] = oauth.new_state()
    session["user_id"] = user["id"]
    return redirect(url_for("web.home"))


@web.route("/password-reset", methods=["GET", "POST"])
@web.route("/forgot-password", methods=["GET", "POST"])
def forgot_password_form() -> str | Any:
    if request.method == "POST":
        try:
            email = schemas.parse_password_reset_request({"email": request.form.get("email", "")})
            passwords.request_password_reset(
                email,
                current_app.extensions["lms_store"],
                current_app.config,
            )
        except ValidationError:
            return render_template("forgot_password.html", error="Vui lòng nhập email hợp lệ."), 400
        except (RuntimeError, OSError, smtplib.SMTPException):
            return render_template(
                "forgot_password.html",
                error="Không thể gửi email lúc này. Vui lòng liên hệ quản trị viên.",
            ), 503
        flash("Nếu email thuộc về tài khoản hợp lệ, hướng dẫn đặt lại mật khẩu sẽ được gửi.")
        return redirect(url_for("web.forgot_password_form"))
    return render_template("forgot_password.html")


@web.route("/reset-password", defaults={"token": None}, methods=["GET", "POST"])
@web.route("/password-reset/<token>", methods=["GET", "POST"])
def password_reset_form(token: str | None = None) -> str | Any:
    token = token or request.args.get("token", "")
    state = current_app.extensions["lms_store"]
    if request.method == "POST":
        password = request.form.get("password", "")
        confirmation = request.form.get("confirm_password", "")
        try:
            schemas.parse_password_reset_confirmation({"token": token, "password": password})
        except ValidationError:
            return render_template(
                "reset_password.html",
                reset_token=token,
                error="Mật khẩu cần có ít nhất 10 ký tự, chữ hoa, chữ thường và chữ số.",
            ), 400
        if password != confirmation:
            return render_template(
                "reset_password.html",
                reset_token=token,
                error="Mật khẩu xác nhận không khớp.",
            ), 400
        if not passwords.reset_password(token, password, state):
            return render_template(
                "reset_password.html",
                reset_token=token,
                error="Liên kết không hợp lệ, đã hết hạn hoặc đã được sử dụng.",
            ), 400
        return redirect(url_for("web.login_form", password_reset="1"))
    valid_token = token != "" and passwords.is_reset_token_valid(token, state)
    return render_template("reset_password.html", reset_token=token if valid_token else None)


# ====================== GIAO DIỆN HỌC TẬP ======================


def _state() -> dict[str, Any]:
    return current_app.extensions["lms_store"]


def _upload_dir(kind: str) -> str:
    key = {
        "avatars": "AVATAR_FOLDER",
        "materials": "MATERIAL_FOLDER",
        "submissions": "SUBMISSION_FOLDER",
    }[kind]
    folder = current_app.config.get(key) or os.path.join(
        current_app.root_path, "..", "data", "uploads", kind
    )
    return os.path.abspath(folder)


def _call(action: Callable[[], Any]) -> Any:
    try:
        with services.using_store(_state()):
            return action()
    except AppError as error:
        abort(getattr(error, "status", 500))


def _can_manage_course(course: dict[str, Any], user: dict[str, Any]) -> bool:
    return user["role"] == "ADMIN" or (
        user["role"] == "INSTRUCTOR" and course["instructorId"] == user["id"]
    )


# ---------- Hồ sơ ----------


@web.post("/account/profile")
@login_required
def update_profile_form() -> Any:
    body = {
        "fullName": request.form.get("fullName", ""),
        "bio": request.form.get("bio", ""),
        "phone": request.form.get("phone", ""),
    }
    try:
        updates = schemas.parse_profile_update_body(body)
        with services.using_store(_state()):
            account_service.update_profile(g.web_user, updates)
    except (ValidationError, AppError):
        flash("Thông tin hồ sơ không hợp lệ.", "error")
    else:
        flash("Đã cập nhật hồ sơ.", "info")
    return redirect(url_for("web.account"))


@web.post("/account/password")
@login_required
def change_password_form() -> Any:
    old = request.form.get("oldPassword", "")
    new = request.form.get("newPassword", "")
    confirm = request.form.get("confirmPassword", "")
    if new != confirm:
        flash("Mật khẩu xác nhận không khớp.", "error")
        return redirect(url_for("web.account"))
    try:
        schemas.parse_password_change_body({"oldPassword": old, "newPassword": new})
        with services.using_store(_state()):
            account_service.change_password(g.web_user, old, new)
    except InvalidCredentials:
        flash("Mật khẩu hiện tại không đúng.", "error")
    except (ValidationError, AppError):
        flash("Mật khẩu mới cần ≥ 10 ký tự, có chữ hoa, chữ thường và chữ số.", "error")
    else:
        flash("Đã đổi mật khẩu. Hãy đăng nhập lại.", "info")
        session.clear()
        return redirect(url_for("web.login_form"))
    return redirect(url_for("web.account"))


@web.post("/account/avatar")
@login_required
def upload_avatar_form() -> Any:
    file = request.files.get("avatar")
    if file is None or not file.filename:
        flash("Chọn một tệp ảnh trước khi tải lên.", "error")
        return redirect(url_for("web.account"))
    filename = file.filename
    try:
        _call(
            lambda: account_service.update_avatar(
                g.web_user, file.read(), filename, _upload_dir("avatars")
            )
        )
    except (ValidationError, AppError):
        flash("Ảnh không hợp lệ (chỉ nhận png/jpg/jpeg/gif/webp, tối đa 2MB).", "error")
    else:
        flash("Đã cập nhật ảnh đại diện.", "info")
    return redirect(url_for("web.account"))


@web.get("/ui/avatar/<user_id>")
@login_required
def avatar_file(user_id: str) -> Any:
    path = _call(lambda: account_service.get_avatar_path(user_id, _upload_dir("avatars")))
    if not path:
        abort(404)
    return send_file(path)


# ---------- Khoá học ----------


@web.get("/ui/courses")
@login_required
def courses_list() -> str:
    q = request.args.get("q") or None
    instructor = request.args.get("instructor") or None
    courses = _call(lambda: course_service.list_courses(g.web_user, q, instructor))
    instructors = (
        [user for user in _state()["users"].values() if user["role"] == "INSTRUCTOR"]
        if g.web_user["role"] == "ADMIN"
        else []
    )
    return render_template(
        "courses.html",
        courses=courses,
        q=q or "",
        instructor=instructor or "",
        instructors=instructors,
    )


@web.post("/ui/courses")
@login_required
def create_course_form() -> Any:
    name = request.form.get("name", "")
    instructor_id = request.form.get("instructorId") or str(g.web_user["id"])
    try:
        _call(lambda: course_service.create_course(g.web_user, name, instructor_id))
    except (ValidationError, AppError):
        flash("Không tạo được khoá học (kiểm tra tên và giảng viên).", "error")
    else:
        flash("Đã tạo khoá học.", "info")
    return redirect(url_for("web.courses_list"))


@web.get("/ui/courses/<course_id>")
@login_required
def course_detail(course_id: str) -> str:
    def load() -> dict[str, Any]:
        course = course_service.get_course(g.web_user, course_id)
        return {
            "course": course,
            "members": course_service.list_course_members(g.web_user, course_id),
            "materials": material_service.list_materials(g.web_user, course_id),
            "announcements": forum_service.list_announcements(g.web_user, course_id),
            "assignments": assignment_service.list_assignments(g.web_user, course_id),
            "quizzes": quiz_service.list_quizzes(g.web_user, course_id),
            "threads": forum_service.list_threads(g.web_user, course_id),
        }

    data = _call(load)
    return render_template(
        "course.html",
        can_manage=_can_manage_course(data["course"], g.web_user),
        user=g.web_user,
        **data,
    )


@web.post("/ui/courses/<course_id>/rename")
@login_required
def rename_course_form(course_id: str) -> Any:
    try:
        _call(
            lambda: course_service.update_course(
                g.web_user, course_id, request.form.get("name", "")
            )
        )
    except (ValidationError, AppError):
        flash("Không đổi được tên khoá học.", "error")
    else:
        flash("Đã cập nhật khoá học.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


@web.post("/ui/courses/<course_id>/delete")
@login_required
def delete_course_form(course_id: str) -> Any:
    try:
        _call(lambda: course_service.delete_course(g.web_user, course_id))
    except AppError:
        flash("Không xoá được khoá học.", "error")
        return redirect(url_for("web.course_detail", course_id=course_id))
    flash("Đã xoá khoá học.", "info")
    return redirect(url_for("web.courses_list"))


# ---------- Tài liệu ----------


@web.post("/ui/courses/<course_id>/materials")
@login_required
def upload_material_form(course_id: str) -> Any:
    file = request.files.get("file")
    title = request.form.get("title", "")
    if file is None or not file.filename:
        flash("Chọn tệp tài liệu trước khi tải lên.", "error")
        return redirect(url_for("web.course_detail", course_id=course_id))
    filename = file.filename
    try:
        _call(
            lambda: material_service.create_material(
                g.web_user,
                course_id,
                title,
                file.read(),
                filename,
                _upload_dir("materials"),
            )
        )
    except (ValidationError, AppError):
        flash("Tệp không hợp lệ hoặc bạn không có quyền.", "error")
    else:
        flash("Đã tải tài liệu lên.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


@web.get("/ui/materials/<material_id>/download")
@login_required
def download_material(material_id: str) -> Any:
    path, filename = _call(
        lambda: material_service.get_material_for_download(
            g.web_user, material_id, _upload_dir("materials")
        )
    )
    return send_file(path, download_name=filename, as_attachment=True)


@web.post("/ui/materials/<material_id>/delete")
@login_required
def delete_material_form(material_id: str) -> Any:
    def remove() -> str:
        material = store.get_material(_state(), material_id)
        if material is None:
            raise NotFound()
        material_service.delete_material(g.web_user, material_id, _upload_dir("materials"))
        return material["courseId"]

    course_id = _call(remove)
    flash("Đã xoá tài liệu.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


# ---------- Thông báo ----------


@web.post("/ui/courses/<course_id>/announcements")
@login_required
def create_announcement_form(course_id: str) -> Any:
    try:
        _call(
            lambda: forum_service.create_announcement(
                g.web_user,
                course_id,
                request.form.get("title", ""),
                request.form.get("body", ""),
            )
        )
    except (ValidationError, AppError):
        flash("Không đăng được thông báo.", "error")
    else:
        flash("Đã đăng thông báo.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


@web.post("/ui/announcements/<announcement_id>/delete")
@login_required
def delete_announcement_form(announcement_id: str) -> Any:
    def remove() -> str:
        announcement = store.get_announcement(_state(), announcement_id)
        if announcement is None:
            raise NotFound()
        forum_service.delete_announcement(g.web_user, announcement_id)
        return announcement["courseId"]

    course_id = _call(remove)
    flash("Đã xoá thông báo.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


# ---------- Bài tập ----------


@web.post("/ui/courses/<course_id>/assignments")
@login_required
def create_assignment_form(course_id: str) -> Any:
    try:
        due_at = schemas.parse_due_at(request.form.get("dueAt", ""))
        _call(
            lambda: assignment_service.create_assignment(
                g.web_user,
                course_id,
                request.form.get("title", ""),
                request.form.get("description", ""),
                due_at,
            )
        )
    except (ValidationError, AppError):
        flash("Không tạo được bài tập (kiểm tra tên và hạn nộp).", "error")
    else:
        flash("Đã tạo bài tập.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


@web.get("/ui/assignments/<assignment_id>")
@login_required
def assignment_detail(assignment_id: str) -> str:
    def load() -> dict[str, Any]:
        assignment = store.get_assignment(_state(), assignment_id)
        if assignment is None:
            raise NotFound()
        submissions = assignment_service.list_submissions(g.web_user, assignment_id)
        course = _state()["courses"].get(assignment["courseId"])
        return {
            "assignment": assignment,
            "submissions": submissions,
            "course": course,
        }

    data = _call(load)
    course = data["course"] or {}
    return render_template(
        "assignment.html",
        user=g.web_user,
        can_manage=bool(course) and _can_manage_course(course, g.web_user),
        **data,
    )


@web.post("/ui/assignments/<assignment_id>/submit")
@login_required
def submit_assignment_form(assignment_id: str) -> Any:
    content = request.form.get("content", "").strip()
    file = request.files.get("file")
    stored_name = ""
    clean_name = ""
    try:
        if file is not None and file.filename:
            stored_name, clean_name, _ = storage.secure_save_file(
                file.read(),
                file.filename,
                _upload_dir("submissions"),
                allowed_extensions=storage.ALLOWED_SUBMISSION_EXTENSIONS,
                max_bytes=storage.MAX_SUBMISSION_BYTES,
            )
        if not content and not clean_name:
            raise ValidationError()
        if not content:
            content = f"Uploaded file: {clean_name}"
        _call(
            lambda: assignment_service.submit(
                g.web_user,
                assignment_id,
                content,
                file_name=clean_name,
                file_path=stored_name,
            )
        )
    except (ValidationError, AppError):
        flash("Không nộp được bài (kiểm tra tệp và nội dung).", "error")
    else:
        flash("Đã nộp bài.", "info")
    return redirect(url_for("web.assignment_detail", assignment_id=assignment_id))


@web.get("/ui/submissions/<submission_id>/download")
@login_required
def download_submission(submission_id: str) -> Any:
    path, filename = _call(
        lambda: assignment_service.get_submission_file(
            g.web_user, submission_id, _upload_dir("submissions")
        )
    )
    return send_file(path, download_name=filename, as_attachment=True)


@web.post("/ui/submissions/<submission_id>/grade")
@login_required
def grade_submission_form(submission_id: str) -> Any:
    try:
        grade = float(request.form.get("grade", ""))
    except ValueError:
        flash("Điểm không hợp lệ.", "error")
        return redirect(request.referrer or url_for("web.home"))
    feedback = request.form.get("feedback", "")
    try:
        _call(
            lambda: assignment_service.grade_submission(g.web_user, submission_id, grade, feedback)
        )
    except (ValidationError, AppError):
        flash("Không chấm được điểm (0–10).", "error")
    else:
        flash("Đã lưu điểm.", "info")
    return redirect(request.referrer or url_for("web.home"))


# ---------- Quiz ----------


def _parse_questions(raw: str) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            raise ValidationError()
        question = parts[0]
        options = parts[1:-1]
        correct = int(parts[-1])
        questions.append(
            {
                "question": question,
                "options": options,
                "correctOption": correct,
                "points": 1.0,
            }
        )
    if not questions:
        raise ValidationError()
    return questions


@web.post("/ui/courses/<course_id>/quizzes")
@login_required
def create_quiz_form(course_id: str) -> Any:
    try:
        questions = _parse_questions(request.form.get("questions", ""))
        _call(
            lambda: quiz_service.create_quiz(
                g.web_user,
                course_id=course_id,
                title=request.form.get("title", ""),
                description=request.form.get("description", ""),
                duration_minutes=int(request.form.get("durationMinutes", "10")),
                max_attempts=int(request.form.get("maxAttempts", "1")),
                questions=questions,
            )
        )
    except (ValueError, ValidationError, AppError):
        flash("Không tạo được quiz (kiểm tra câu hỏi và thời lượng).", "error")
    else:
        flash("Đã tạo quiz.", "info")
    return redirect(url_for("web.course_detail", course_id=course_id))


@web.get("/ui/quizzes/<quiz_id>")
@login_required
def quiz_detail(quiz_id: str) -> str:
    quiz = _call(lambda: quiz_service.get_quiz(g.web_user, quiz_id))
    attempts = _call(lambda: quiz_service.list_attempts(g.web_user, quiz_id))
    course = _state()["courses"].get(quiz["courseId"]) or {}
    return render_template(
        "quiz.html",
        user=g.web_user,
        quiz=quiz,
        attempts=attempts,
        can_manage=bool(course) and _can_manage_course(course, g.web_user),
    )


@web.post("/ui/quizzes/<quiz_id>/attempts")
@login_required
def start_quiz_attempt(quiz_id: str) -> Any:
    attempt = _call(lambda: quiz_service.start_attempt(g.web_user, quiz_id))
    return redirect(url_for("web.quiz_attempt", attempt_id=attempt["id"]))


@web.get("/ui/quiz-attempts/<attempt_id>")
@login_required
def quiz_attempt(attempt_id: str) -> str:
    attempt = _call(lambda: store.get_quiz_attempt(_state(), attempt_id))
    if attempt is None or attempt["studentId"] != g.web_user["id"]:
        abort(404)
    quiz = _call(lambda: quiz_service.get_quiz(g.web_user, attempt["quizId"]))
    elapsed = _state()["now"]() - attempt["startedAt"]
    remaining = max(0, int(quiz["durationMinutes"] * 60 - elapsed))
    return render_template("attempt.html", quiz=quiz, attempt=attempt, remaining=remaining)


@web.post("/ui/quiz-attempts/<attempt_id>/submit")
@login_required
def submit_quiz_attempt_form(attempt_id: str) -> Any:
    attempt = _call(lambda: store.get_quiz_attempt(_state(), attempt_id))
    if attempt is None or attempt["studentId"] != g.web_user["id"]:
        abort(404)
    quiz = _call(lambda: quiz_service.get_quiz(g.web_user, attempt["quizId"]))
    answers: dict[str, int] = {}
    for question in quiz.get("questions", []):
        value = request.form.get(f"q_{question['id']}")
        if value is not None and value.isdigit():
            answers[question["id"]] = int(value)
    result = _call(lambda: quiz_service.submit_attempt(g.web_user, attempt_id, answers))
    flash(f"Đã nộp bài. Điểm: {result['score']}/10", "info")
    return redirect(url_for("web.quiz_detail", quiz_id=attempt["quizId"]))


@web.post("/ui/quizzes/<quiz_id>/delete")
@login_required
def delete_quiz_form(quiz_id: str) -> Any:
    quiz = _call(lambda: quiz_service.get_quiz(g.web_user, quiz_id))
    _call(lambda: quiz_service.delete_quiz(g.web_user, quiz_id))
    flash("Đã xoá quiz.", "info")
    return redirect(url_for("web.course_detail", course_id=quiz["courseId"]))


# ---------- Diễn đàn ----------


@web.post("/ui/courses/<course_id>/threads")
@login_required
def create_thread_form(course_id: str) -> Any:
    try:
        thread = _call(
            lambda: forum_service.create_thread(
                g.web_user,
                course_id,
                request.form.get("title", ""),
                request.form.get("body", ""),
            )
        )
    except (ValidationError, AppError):
        flash("Không tạo được chủ đề.", "error")
        return redirect(url_for("web.course_detail", course_id=course_id))
    return redirect(url_for("web.thread_detail", thread_id=thread["id"]))


@web.get("/ui/threads/<thread_id>")
@login_required
def thread_detail(thread_id: str) -> str:
    thread = _call(lambda: store.get_thread(_state(), thread_id))
    if thread is None:
        abort(404)
    _call(lambda: forum_service.authorize_thread_view(g.web_user, thread_id))
    comments = _call(lambda: forum_service.list_comments(g.web_user, thread_id))
    course = _state()["courses"].get(thread["courseId"]) or {}
    can_manage = bool(course) and _can_manage_course(course, g.web_user)
    return render_template(
        "thread.html",
        thread=thread,
        comments=comments,
        user=g.web_user,
        can_manage=can_manage,
    )


@web.post("/ui/threads/<thread_id>/update")
@login_required
def update_thread_form(thread_id: str) -> Any:
    try:
        _call(
            lambda: forum_service.update_thread(
                g.web_user,
                thread_id,
                request.form.get("title", ""),
                request.form.get("body", ""),
            )
        )
    except (ValidationError, AppError):
        flash("Không sửa được chủ đề.", "error")
    else:
        flash("Đã cập nhật chủ đề.", "info")
    return redirect(url_for("web.thread_detail", thread_id=thread_id))


@web.post("/ui/threads/<thread_id>/delete")
@login_required
def delete_thread_form(thread_id: str) -> Any:
    thread = _call(lambda: store.get_thread(_state(), thread_id))
    if thread is None:
        abort(404)
    _call(lambda: forum_service.delete_thread(g.web_user, thread_id))
    flash("Đã xoá chủ đề.", "info")
    return redirect(url_for("web.course_detail", course_id=thread["courseId"]))


@web.post("/ui/threads/<thread_id>/comments")
@login_required
def create_comment_form(thread_id: str) -> Any:
    try:
        _call(
            lambda: forum_service.create_comment(
                g.web_user, thread_id, request.form.get("body", "")
            )
        )
    except (ValidationError, AppError):
        flash("Không gửi được bình luận.", "error")
    else:
        flash("Đã gửi bình luận.", "info")
    return redirect(url_for("web.thread_detail", thread_id=thread_id))


@web.post("/ui/comments/<comment_id>/update")
@login_required
def update_comment_form(comment_id: str) -> Any:
    comment = _call(lambda: store.get_comment(_state(), comment_id))
    if comment is None:
        abort(404)
    try:
        _call(
            lambda: forum_service.update_comment(
                g.web_user, comment_id, request.form.get("body", "")
            )
        )
    except (ValidationError, AppError):
        flash("Không sửa được bình luận.", "error")
    else:
        flash("Đã cập nhật bình luận.", "info")
    return redirect(url_for("web.thread_detail", thread_id=comment["threadId"]))


@web.post("/ui/comments/<comment_id>/delete")
@login_required
def delete_comment_form(comment_id: str) -> Any:
    comment = _call(lambda: store.get_comment(_state(), comment_id))
    if comment is None:
        abort(404)
    _call(lambda: forum_service.delete_comment(g.web_user, comment_id))
    flash("Đã xoá bình luận.", "info")
    return redirect(url_for("web.thread_detail", thread_id=comment["threadId"]))


# ---------- Quản trị ----------


@web.get("/ui/admin")
@login_required
def admin_panel() -> str:
    if g.web_user["role"] != "ADMIN":
        abort(403)
    users = _call(lambda: admin_service.list_users(g.web_user))
    entries = _call(lambda: admin_service.read_audit(g.web_user, 50))
    return render_template("admin.html", users=users, entries=entries)


@web.post("/ui/admin/users/<user_id>/role")
@login_required
def change_role_form(user_id: str) -> Any:
    try:
        _call(
            lambda: admin_service.change_role(
                g.web_user, user_id, request.form.get("role", "STUDENT")
            )
        )
    except (ValidationError, AppError):
        flash("Không đổi được vai trò.", "error")
    else:
        flash("Đã đổi vai trò.", "info")
    return redirect(url_for("web.admin_panel"))


@web.post("/ui/admin/users/<user_id>/lock")
@login_required
def lock_user_form(user_id: str) -> Any:
    _call(lambda: admin_service.set_locked(g.web_user, user_id, True))
    flash("Đã khoá tài khoản.", "info")
    return redirect(url_for("web.admin_panel"))


@web.post("/ui/admin/users/<user_id>/unlock")
@login_required
def unlock_user_form(user_id: str) -> Any:
    _call(lambda: admin_service.set_locked(g.web_user, user_id, False))
    flash("Đã mở khoá tài khoản.", "info")
    return redirect(url_for("web.admin_panel"))
