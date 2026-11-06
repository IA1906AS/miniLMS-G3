# MiniLMS

MiniLMS là một hệ quản lý học tập nhỏ (Flask + SQLite) dùng cho bài tập nhóm: quản lý
tài khoản, khóa học, điểm, đăng ký khóa học và email xác nhận. Mục tiêu kép: giữ các bất
biến bảo mật (JWT, CSRF, phân quyền, audit) và minh họa **defensive pattern #8 —
transactional outbox** trên một luồng nghiệp vụ thật.

> Đây là **nguồn thông tin duy nhất** (single source of truth) của dự án. Quy ước code ở
> [docs/conventions.md](docs/conventions.md), quyết định kỹ thuật ở
> [docs/decisions/](docs/decisions/), luật làm việc cho agent ở [AGENTS.md](AGENTS.md).

## 1. Stack

| Thành phần | Lựa chọn | ADR |
|---|---|---|
| Ngôn ngữ | Python 3.11+ (dev hiện tại 3.14, CI 3.11–3.13) | — |
| Web | Flask 3 | [0001](docs/decisions/0001-flask-monolith.md) |
| Dữ liệu | SQLite qua `sqlite3`, SQL thuần | [0002](docs/decisions/0002-sqlite-raw-sql.md) |
| Test | pytest 9 + pytest-cov, ngưỡng 80% | [0003](docs/decisions/0003-pytest-va-coverage.md) |
| Chất lượng | ruff (format + lint) + mypy cơ bản | [0004](docs/decisions/0004-ruff-mypy.md) |
| Bảo mật | JWT, cookie phiên `HttpOnly`, CSRF, RBAC, audit JSONL | — |
| Giao nhận email | Transactional outbox + SMTP | [0005](docs/decisions/0005-outbox-email-dang-ky.md) |

## 2. Kiến trúc

```
Trình duyệt / API client
        │
        ▼
app/gate.py            nạp lại cache, CSRF (nếu có phiên), xác thực Bearer
        │
        ├── app/web.py            HTML (Jinja) + phiên cookie
        └── app/__init__.py       JSON API + CLI (`flask outbox ...`)
                    │
                    ▼
            app/services.py       nghiệp vụ + phân quyền (kiểm tra lại lần 2)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
   app/store.py             app/outbox.py
   SQL + transaction        claim / gửi / SENT · DEAD
                                 │
                                 ▼
                           app/emailer.py  (SMTP)
```

| Module | Trách nhiệm |
|---|---|
| `app/gate.py` | `before_request`: refresh cache, chặn request chưa xác thực |
| `app/guards.py` | `require_role` cho route JSON |
| `app/auth.py` | đăng nhập, phát/kiểm tra JWT |
| `app/passwords.py` | reset mật khẩu (token dùng một lần, hết hạn 30 phút) |
| `app/oauth.py` | Google/GitHub OAuth (PKCE, state) |
| `app/schemas.py` | validate dữ liệu vào |
| `app/services.py` | nghiệp vụ điểm, đăng ký khóa học |
| `app/store.py` | toàn bộ SQL, transaction, cache |
| `app/outbox.py` | pattern #8: ghi sự kiện, drain, retry, DEAD |
| `app/extended.py` | GĐ3: blueprint phân quyền mở rộng |
| `app/emailer.py` | dựng và gửi email qua SMTP |
| `app/audit.py` | audit log JSONL (không chứa bí mật) |
| `app/errors.py` | `AppError` → JSON `{"error": "<CODE>"}` |

## 3. Cài đặt và chạy

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt   # gồm cả requirements.txt
Copy-Item .env.example .env
```

Điền `.env` (hoặc biến môi trường) theo [.env.example](.env.example). Tối thiểu:

| Biến | Bắt buộc | Ghi chú |
|---|---|---|
| `JWT_SECRET` | Có | ≥ 32 ký tự; thiếu thì app không khởi động |
| `DATABASE_PATH` | Không | mặc định `lms.sqlite3`; test dùng `:memory:` |
| `PUBLIC_BASE_URL` | Không | origin dùng trong link reset/OAuth; HTTPS khi deploy |
| `SMTP_HOST`, `SMTP_FROM` | Khi gửi mail | thiếu thì outbox đẩy event sang `DEAD` sau số lần thử |
| `OUTBOX_*` | Không | xem mục 6 |

```powershell
$env:JWT_SECRET = "replace-with-a-random-secret-of-32-or-more-characters"
flask --app app run
```

OAuth (tùy chọn): thêm callback `{PUBLIC_BASE_URL}/oauth/google/callback` và
`.../oauth/github/callback`, rồi đặt `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`,
`GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`. Hệ thống **không** tự liên kết OAuth identity
với tài khoản cùng email.

Dữ liệu mẫu lấy từ `app/seed.json` (6 tài khoản, 2 khóa học). Trước khi triển khai thật:
đổi mật khẩu demo, bảo vệ secret/SMTP, chạy sau HTTPS (`SESSION_COOKIE_SECURE=true`).

## 4. Bề mặt HTTP

| Route | Mô tả |
|---|---|
| `GET /`, `/login`, `/register`, `/forgot-password`, `/reset-password?token=...`, `/account` | giao diện |
| `POST /auth/login`, `/auth/register`, `/auth/forgot-password`, `/auth/reset-password` | API JSON |
| `GET /me` | thông tin actor từ JWT |
| `GET /courses/<id>/grades`, `PUT /courses/<id>/grades/<student_id>` | xem/sửa điểm |
| `GET /courses`, `GET /courses/<id>` | danh sách/chi tiết môn theo quyền (GĐ3) |
| `POST /courses/<id>/enrollments`, `DELETE .../enrollments/<student_id>` | ADMIN/GV quản lý ghi danh |
| `GET /me/grades` | sinh viên xem điểm của chính mình |
| `GET /admin/users`, `PATCH /admin/users/<id>/role` | quản trị người dùng (ADMIN) |
| `POST /auth/logout` | vô hiệu token hiện tại (mọi vai trò) |
| `POST /me/password`, `GET`, `PUT /users/me` | đổi mật khẩu, xem/sửa hồ sơ (bước 3.1) |
| `POST /me/enrollments` `{"courseId": ...}` | sinh viên tự đăng ký (kèm outbox) |
| `POST /courses/<id>/enroll` | đăng ký từ giao diện (CSRF) |

Request JSON dùng `Authorization: Bearer <token>`; form HTML dùng CSRF token. Đăng nhập
qua trình duyệt dùng cookie phiên `HttpOnly` (30 ngày nếu chọn ghi nhớ).

## 5. Test và quality gate

```powershell
python -m pytest -q                                   # 132 test, ~130s
python -m pytest -q --cov=app --cov-report=term-missing
powershell -File scripts/gate.ps1                     # gate đầy đủ
pre-commit install                                    # hook tầng 1
```

Gate gồm: `ruff format --check`, `ruff check`, `mypy app`, `pytest` với
`--cov-fail-under=80`, `pip-audit`, semgrep (nếu cài), và gitleaks ở CI. CI
(`.github/workflows/ci.yml`) chạy trên Python 3.11/3.12/3.13; `.github/workflows/semgrep.yml`
quét bảo mật riêng. Chi tiết hai tầng: [ADR 0006](docs/decisions/0006-quality-gate-2-tang.md).

## 6. Defensive pattern #8 — transactional outbox

Đăng ký khóa học ghi `enrollments` **và** `outbox_events(PENDING)` trong cùng một
transaction; dispatcher gửi email at-least-once. SMTP lỗi hay tiến trình chết đều không làm
mất sự kiện.

- Bảng `outbox_events`: `PENDING → SENDING → SENT`, hoặc `DEAD` sau
  `OUTBOX_MAX_ATTEMPTS`; event `SENDING` quá lease được trả về `PENDING` (khôi phục sau crash).
- `flask outbox drain [--limit N]`, `flask outbox status`, hoặc `OUTBOX_POLL_INTERVAL > 0`
  để chạy worker nền.
- Email có `Message-ID: <eventId@lms.local>` để phía nhận chống trùng (at-least-once).
- Cấu hình: `OUTBOX_MAX_ATTEMPTS` (5), `OUTBOX_RETRY_DELAY_SECONDS` (2),
  `OUTBOX_LEASE_SECONDS` (60), `OUTBOX_BATCH_SIZE` (10), `OUTBOX_POLL_INTERVAL` (0).
  Test bơm `MAIL_TRANSPORT` thay cho SMTP thật.

Thiết kế, tiêu chí nghiệm thu và kịch bản demo:
[docs/de-xuat-defensive-pattern.md](docs/de-xuat-defensive-pattern.md).

## 7. Trạng thái

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Đăng ký/đăng nhập, JWT, phiên cookie, CSRF | Xong | có test bảo mật |
| Quên/đặt lại mật khẩu | Xong | token một lần, hết hạn 30 phút |
| OAuth Google/GitHub | Xong | cần client id/secret để dùng thật |
| Xem/sửa điểm + RBAC + audit | Xong | chưa có optimistic locking |
| Pattern #8: đăng ký khóa học + outbox | Xong | [ADR 0005](docs/decisions/0005-outbox-email-dang-ky.md) |
| GĐ3: phân quyền mở rộng (8 endpoint) | Xong | [ADR 0007](docs/decisions/0007-giai-doan-3-phan-quyen.md) |
| GĐ3 bước 3.1: logout, đổi mật khẩu, hồ sơ | Xong | [ADR 0008](docs/decisions/0008-token-vo-hieu-theo-giay.md) |
| GĐ3 bước 3.2–3.6: khoá học, quản trị, bài tập, diễn đàn, version | Chưa làm | làm theo từng bước, chờ duyệt |
| Quality gate + CI | Xong | [ADR 0006](docs/decisions/0006-quality-gate-2-tang.md) |
| Pattern #3: optimistic locking khi sửa điểm | Chưa làm | kế hoạch trong tài liệu pattern |
| UI quản trị người dùng/ghi danh | Chưa làm | mới có API |
| Worker outbox chạy nền mặc định | Chưa bật | cần `OUTBOX_POLL_INTERVAL > 0` hoặc cron `flask outbox drain` |

## 8. Tài liệu

| File | Nội dung |
|---|---|
| [AGENTS.md](AGENTS.md) | quy trình, lệnh, việc không được làm |
| [DeepSeek.md](DeepSeek.md) | điểm vào cho agent DeepSeek |
| [docs/conventions.md](docs/conventions.md) | đặt tên, lỗi, test, commit |
| [docs/decisions/](docs/decisions/) | ADR + template |
| [docs/de-xuat-defensive-pattern.md](docs/de-xuat-defensive-pattern.md) | phân tích 10 pattern, thiết kế #3/#8 |
