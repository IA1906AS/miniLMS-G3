# Burp Suite — hướng dẫn scan MiniLMS

## 1. Môi trường

- App: `http://127.0.0.1:5001` (chạy bằng `pentest_run.py`)
- DB: `lms_pentest` — **chỉ dùng cho test**, không phải DB `lms`
- Burp: `2026.2.4-46047 Burp Suite Professional`
- Project: `.pentest/burp/miniLMS.burp` (Burp đã mở sẵn)
- Request pack: `.pentest/burp/requests/*.http`
- Token test: `.pentest/burp/tokens.json` (hết hạn sau 8 giờ)

Tài khoản seed:

| Vai trò | Email | Mật khẩu |
|---|---|---|
| ADMIN | `admin@lms.test` | `Lms@2026` |
| INSTRUCTOR (c1) | `an.gv@lms.test` | `Lms@2026` |
| INSTRUCTOR (c2) | `binh.gv@lms.test` | `Lms@2026` |
| STUDENT (c1) | `chi.sv@lms.test` | `Lms@2026` |
| STUDENT (c1,c2) | `dung.sv@lms.test` | `Lms@2026` |

## 2. Việc cần làm trên Burp

### Bước 1 — Kiểm tra project

Cửa sổ Burp đã mở với project `miniLMS.burp`. Nếu Burp hỏi chọn project, chọn:

```
D:\miniLMS-G3-main\.pentest\burp\miniLMS.burp
```

### Bước 2 — Đặt scope

`Target` → `Scope` → `Add`:

```
http://127.0.0.1:5001
```

Chỉ scan host này. Không thêm host khác.

### Bước 3 — Gửi request pack

Mở từng file trong `.pentest/burp/requests/`, copy toàn bộ nội dung, dán vào **Repeater** và bấm **Send**.

Thứ tự gợi ý:

| File | Kỳ vọng | Mục đích |
|---|---|---|
| `01-login-admin.http` | 200 | lấy token admin mới |
| `02-login-instructor.http` | 200 | token GV |
| `03-login-student.http` | 200 | token SV |
| `04-me-admin.http` | 200 | token hợp lệ |
| `05-idor-student-c2.http` | 403 | SV xem môn chưa ghi danh |
| `06-idor-student-admin.http` | 403 | SV gọi API admin |
| `07-idor-instructor-c2.http` | 403 | GV xem điểm môn khác |
| `08-grade-v2-get.http` | 200 | đọc version điểm |
| `09-grade-v2-stale.http` | 409 | optimistic locking |
| `10-grade-core-bypass.http` | 200 | endpoint cũ ghi đè |
| `11-enroll-duplicate.http` | 409 | ghi danh trùng |
| `12-reset-existing.http` | 503 | email tồn tại + SMTP lỗi |
| `13-reset-missing.http` | 202 | email không tồn tại |
| `14-members-pii.http` | 200 | email/phone thành viên |
| `15-thread-xss.http` | 201 | tạo thread chứa `<script>` |
| `16-upload-php.http` | 400 | chặn file `.php` |
| `17-jwt-none.http` | 401 | JWT `alg=none` |
| `18-admin-audit.http` | 200 | audit admin |
| `19-openapi.http` | 200 | OpenAPI công khai |
| `20-idor-binh-c1.http` | 403 | GV c2 xem member c1 |

Token trong pack là token test, hết hạn sau 8 giờ. Muốn refresh:

```powershell
.\.venv\Scripts\python.exe .pentest\burp\prepare_requests.py
```

### Bước 4 — Scan

**Cách A — scan toàn app (khuyến nghị):**

1. `Proxy` → tắt `Intercept is on`.
2. `Proxy` → `Open browser`.
3. Trong Burp browser, mở `http://127.0.0.1:5001/login`, đăng nhập `admin@lms.test / Lms@2026`.
4. Duyệt các trang: `/ui/courses`, `/ui/courses/c1`, `/account`, `/ui/admin`, `/ui/courses/c2`.
5. `Target` → `Site map` → chuột phải `http://127.0.0.1:5001` → **Scan**.
6. Chọn `Crawl and audit` (hoặc `Audit` nếu chỉ muốn audit các request đã có).

**Cách B — scan một request cụ thể:**

- Trong Repeater, chuột phải request → **Scan**.
- Phù hợp để xác nhận một nghi vấn (IDOR, XSS, upload) mà không crawl toàn bộ.

> Lưu ý: Active scan có thể submit form và tạo/xoá dữ liệu. Chỉ chạy trên DB `lms_pentest`; không chạy trên `lms` hay production. Nếu muốn tránh xoá, bỏ các request `DELETE` khỏi scope.

### Bước 5 — Xuất report

`Scanner` → `Issues` → chọn issue → **Report** → xuất XML/HTML:

```
D:\miniLMS-G3-main\.pentest\burp\report.xml
```

Gửi lại đường dẫn report (hoặc nội dung) để mình phân tích, đối chiếu với báo cáo pentest hiện có.

## 3. Gợi ý cấu hình scan

- **Scan type:** Crawl and audit.
- **Scope:** chỉ `127.0.0.1:5001`.
- **Authentication:** dùng Burp browser đã đăng nhập; không cần session handling rule nếu giữ cookie.
- **Insertion points:** mặc định; thêm header `Authorization` nếu scan API.
- **Destructive actions:** tránh các endpoint `DELETE`/`/lock` nếu chỉ muốn scan không phá huỷ; dùng DB test nếu chấp nhận.

## 4. Những gì Burp có thể tìm thêm

- Reflected/stored XSS ở các trường `title`, `body`, `bio`, `feedback`.
- SQLi ở các query `q`, `instructor`, `limit`.
- Path traversal ở material/submission download.
- Missing headers, cookie flags, clickjacking.
- IDOR và privilege escalation ở API.
- Verb tampering, HTTP method issues.

Các lỗi mình đã xác nhận thủ công (xem `docs/bao-cao-pentest-miniLMS.md`):

- F-01: khoá tài khoản không huỷ phiên web.
- F-02: reset password lộ email tồn tại khi SMTP lỗi.
- F-03: lockout DoS theo email.
- F-04: đổi mật khẩu API không huỷ phiên web.
- F-05: xoá course có material trả 500.
- F-06..F-13: headers, cookie, PII, password policy, upload memory, logout same-second, grade bypass.
