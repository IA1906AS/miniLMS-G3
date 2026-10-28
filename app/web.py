import hmac
import secrets
import smtplib
import time
from functools import wraps
from typing import Any, Callable, TypeVar, cast

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from . import auth, oauth, passwords, schemas, store
from .errors import AccountLocked, Conflict, InvalidCredentials, ValidationError


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
            return render_template(
                "login.html", error="Email hoặc mật khẩu không chính xác."
            ), 401
        session.clear()
        session["user_id"] = user["id"]
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
                request.form.get("password")
                != request.form.get("confirm_password")
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
            return render_template(
                "register.html", error="Email này đã được đăng ký."
            ), 409
        return redirect(url_for("web.login_form", registered="1"))
    return render_template("register.html")


@web.get("/account")
@login_required
def account() -> str:
    user = g.web_user
    state = current_app.extensions["lms_store"]
    if user["role"] == "STUDENT":
        courses = [
            {
                **state["courses"][course_id],
                "score": score,
            }
            for (course_id, student_id), score in state["enrollments"].items()
            if student_id == user["id"] and course_id in state["courses"]
        ]
    elif user["role"] == "INSTRUCTOR":
        courses = [
            course
            for course in state["courses"].values()
            if course["instructorId"] == user["id"]
        ]
    else:
        courses = list(state["courses"].values())
    return render_template("account.html", user=user, courses=courses)


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
        f"{current_app.config['PUBLIC_BASE_URL']}"
        f"{url_for('web.oauth_callback', provider=provider)}"
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
            f"Đăng nhập {provider.title()} chưa được cấu hình. Vui lòng dùng email hoặc liên hệ quản trị viên.",
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
        f"{current_app.config['PUBLIC_BASE_URL']}"
        f"{url_for('web.oauth_callback', provider=provider)}"
    )
    try:
        profile = oauth.fetch_profile(
            provider, current_app.config, code, redirect_uri, verifier
        )
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
            email = schemas.parse_password_reset_request(
                {"email": request.form.get("email", "")}
            )
            passwords.request_password_reset(
                email,
                current_app.extensions["lms_store"],
                current_app.config,
            )
        except ValidationError:
            return render_template(
                "forgot_password.html", error="Vui lòng nhập email hợp lệ."
            ), 400
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
            schemas.parse_password_reset_confirmation(
                {"token": token, "password": password}
            )
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
        if not passwords.reset_password(
            token, password, state
        ):
            return render_template(
                "reset_password.html",
                reset_token=token,
                error="Liên kết không hợp lệ, đã hết hạn hoặc đã được sử dụng.",
            ), 400
        return redirect(url_for("web.login_form", password_reset="1"))
    valid_token = passwords.is_reset_token_valid(token, state) if token else False
    return render_template(
        "reset_password.html", reset_token=token if valid_token else None
    )
