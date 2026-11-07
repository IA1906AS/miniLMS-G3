# 0014 — Chuyển tầng lưu trữ từ SQLite sang PostgreSQL

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-07
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/store.py`, `app/__init__.py`, `requirements.txt`, `tests/conftest.py`, `.github/workflows/ci.yml`
- **Thay thế:** [0002](0002-sqlite-raw-sql.md)

## Bối cảnh

Yêu cầu của học phần: hệ thống LMS phải dùng PostgreSQL. Toàn bộ SQL hiện nằm trong một
module `app/store.py` (~2.100 dòng) và dùng các đặc thù SQLite: `sqlite3`, `BEGIN IMMEDIATE`,
`PRAGMA table_info`, `INSERT OR IGNORE`, `AUTOINCREMENT`, placeholder `?`, `COLLATE NOCASE`.

## Quyết định

- Dùng **psycopg 3** (wheel `psycopg[binary]`), kết nối bằng một DSN duy nhất trong biến
  `DATABASE_URL`; bật `autocommit=True` để giữ nguyên mô hình transaction tường minh
  (`BEGIN` / `COMMIT` / `ROLLBACK`) như trước.
- Chuyển đổi cú pháp trong `store.py`:
  - `?` → `%s`
  - `BEGIN IMMEDIATE` → `BEGIN`
  - `PRAGMA table_info(x)` → truy vấn `information_schema.columns`
  - `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`
  - `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGINT GENERATED ALWAYS AS IDENTITY`
  - `REAL` → `DOUBLE PRECISION`, `BLOB` → `BYTEA`
  - bỏ `COLLATE NOCASE`; email đã được chuẩn hoá chữ thường ở tầng nghiệp vụ
  - `executescript` → tách từng câu lệnh DDL
- Giữ nguyên kiến trúc: đúng một module lưu trữ, cache trong RAM, một khoá toàn cục; không đổi
  API, schema nghiệp vụ, route hay giao diện.
- Test dùng `TEST_DATABASE_URL`; `tests/conftest.py` xoá và tạo lại schema `public` trước mỗi
  test để giữ tính độc lập.

## Hệ quả

### Tích cực

- Đáp ứng yêu cầu học phần; dùng được các tính năng PostgreSQL (INDEX, transaction, kiểu dữ liệu).
- Outbox và optimistic locking giữ nguyên logic, chạy đúng trên PostgreSQL.

### Đánh đổi / rủi ro

- Bắt buộc có PostgreSQL khi chạy và khi test; CI phải thêm service `postgres`.
- Không còn chạy được SQLite (đúng yêu cầu, nhưng mất khả năng chạy "không cần cài đặt").
- Test chậm hơn do mỗi test tạo lại schema.

### Việc phải làm kèm theo

- `requirements.txt` thêm `psycopg[binary]`.
- CI thêm service PostgreSQL và biến `TEST_DATABASE_URL`.
- README, `.env.example` cập nhật `DATABASE_URL`.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Giữ SQLite + lớp adapter giả lập cú pháp | Không đáp ứng yêu cầu "dùng PostgreSQL" |
| Chuyển sang SQLAlchemy ORM | Thay đổi quá lớn, không cần thiết cho phạm vi môn học |
| Hỗ trợ song song cả SQLite và PostgreSQL | Hai nhánh hành vi dễ lệch, tăng chi phí bảo trì gấp đôi |
