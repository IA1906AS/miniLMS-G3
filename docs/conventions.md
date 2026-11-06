# Quy ước code — MiniLMS

Tài liệu này là nguồn duy nhất cho quy ước code. Quality gate chạy các quy ước máy kiểm
tra được; phần còn lại do review và `AGENTS.md` bảo đảm.

## 1. Ngôn ngữ và đặt tên

- Định danh, tên hàm, tên bảng, commit message: **tiếng Anh**.
- Chuỗi hiển thị cho người dùng và thông báo lỗi UI: **tiếng Việt**.
- `snake_case` cho biến/hàm/module; `PascalCase` cho lớp; `UPPER_SNAKE_CASE` cho hằng.
- Tên hàm nói hành vi, không nói cơ chế: `enroll_in_course`, `claim_outbox_batch`.
- Tên test: `test_<hành vi>_<điều kiện>` — ví dụ `test_retry_sends_exactly_one_email_after_transient_failure`.

## 2. Cấu trúc thư mục

```
app/
  __init__.py     # create_app: cấu hình, route JSON, CLI
  web.py          # route HTML (Jinja), CSRF
  gate.py         # before_request: nạp lại cache, Bearer, CSRF cho API
  guards.py       # require_role
  auth.py         # đăng nhập, JWT
  passwords.py    # reset mật khẩu
  oauth.py        # Google/GitHub
  services.py     # nghiệp vụ, kiểm tra quyền ở tầng service
  store.py        # toàn bộ SQL + transaction
  schemas.py      # validate/parse dữ liệu vào
  errors.py       # AppError + JSON error handler
  outbox.py       # pattern #8
  audit.py        # audit log JSONL
  emailer.py      # SMTP transport
tests/            # test_<module hoặc hành vi>
docs/             # conventions, ADR
```

Quy tắc: **SQL chỉ nằm trong `store.py`**; route không gọi `store` trực tiếp nếu đã có
service; module mới phải có lý do rõ (mỗi pattern chỉ thêm tối đa 1 module).

## 3. Kiểu dữ liệu

- Mọi hàm public có type hint đầy đủ tham số và giá trị trả về.
- Dùng `X | None` (Python 3.11+), không dùng `Optional[X]`.
- Dữ liệu từ ngoài vào là `Any`/`object`; phải đi qua `schemas.py` trước khi dùng.

## 4. Xử lý lỗi

- Lỗi nghiệp vụ: raise lớp con của `AppError` trong `app/errors.py`, mỗi lớp có
  `status` + `code` (ví dụ `404 NOT_FOUND`, `409 CONFLICT`).
- Response lỗi JSON luôn là `{"error": "<CODE>"}`, không kèm stack trace hay chi tiết nội bộ.
- Kiểm tra quyền ở **cả route (guard) và service**; không tin guard là đủ.
- Lỗi 403 phải ghi audit `ACCESS_DENIED`; không log mật khẩu, token, hay header Authorization.
- Lỗi hạ tầng (SMTP, HTTP ra ngoài) phải được bọc thành lỗi miền hoặc retry có kiểm soát,
  không để rò rỉ exception thô ra response.

## 5. Transaction và dữ liệu

- Mọi thao tác ghi: `BEGIN IMMEDIATE` … `COMMIT`, `ROLLBACK` trong `except`.
- Không gọi mạng/IO bên trong transaction.
- Cột mới phải thêm vào cả `CREATE TABLE` và `SELECT` trong `store.refresh()`.
- Bất biến dữ liệu phải được DB bảo vệ khi có thể (PK, UNIQUE, NOT NULL), không chỉ code.

## 6. Viết test

- pytest, fixture `app` + `client`; mỗi test một hành vi, tên mô tả hành vi.
- Cấu trúc Arrange–Act–Assert; không assert mơ hồ (`assert response`).
- Không gọi mạng/SMTP thật: bơm `MAIL_TRANSPORT` hoặc monkeypatch `app.emailer`.
- Không `sleep` dài; thời gian truyền vào hàm (`now=...`) thay vì chờ thật.
- Test bảo mật phải kiểm tra cả trường hợp **được phép** và **bị từ chối**.
- Coverage không được giảm dưới 80%; test mới không được `skip`/`xfail` để né gate.

## 7. Commit — Conventional Commits

Định dạng: `<type>(<scope>): <mô tả ngắn>` (≤ 72 ký tự, thì hiện tại, tiếng Anh).

| Type | Dùng khi |
|---|---|
| `feat` | Thêm hành vi/tính năng mới |
| `fix` | Sửa lỗi |
| `refactor` | Đổi cấu trúc, không đổi hành vi |
| `docs` | Chỉ tài liệu |
| `test` | Chỉ test |
| `chore` | Cấu hình, dependency, CI |

Ví dụ:

```
feat(outbox): queue enrollment confirmation email in one transaction
fix(auth): reject tokens whose subject no longer exists
docs(adr): record why SQLite is used without an ORM
chore(gate): add ruff, mypy and coverage to pre-commit
```

Quy tắc:

- Mỗi commit **một mục đích**, nhỏ, revert được độc lập.
- Không commit file sinh ra: `.venv/`, `*.sqlite3`, `audit.log`, `.coverage`, `__pycache__/`.
- Không commit secret, `.env`, hay khoá thật — dùng `.env.example`.
- Body (nếu có) giải thích **vì sao**, không kể lại diff.

## 8. Tài liệu và quyết định

- Thông tin dùng chung chỉ viết ở `README.md`, nơi khác link tới.
- Quyết định kỹ thuật mới → thêm ADR trong `docs/decisions/` theo `template.md`.
- Quyết định thay đổi → tạo ADR mới, đánh dấu ADR cũ `Bị thay thế bởi 000X`; **không sửa**
  nội dung ADR cũ.
- Đổi hành vi người dùng thấy được → cập nhật bảng trạng thái trong `README.md`.
