# 0001 — Dùng Flask monolith cho MiniLMS

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS

## Bối cảnh

MiniLMS là bài tập nhóm 2 người: quản lý tài khoản, khóa học, điểm và một vài luồng
nghiệp vụ nhỏ (đăng ký khóa học, email xác nhận). Thời gian ngắn, không có hạ tầng
riêng, cần chạy và demo trên máy cá nhân. Yêu cầu bảo mật (JWT, CSRF, phân quyền,
audit log) phải nằm trong code của nhóm chứ không dựa vào dịch vụ ngoài.

## Quyết định

Dùng **một ứng dụng Flask duy nhất** trong `app/`:

- `create_app()` trong `app/__init__.py` dựng cấu hình, store, error handler, gate và route JSON.
- Giao diện server-side render bằng Jinja (`app/web.py`, `app/templates/`).
- API JSON cho client/CLI dùng chung tầng service và store với giao diện.

## Hệ quả

### Tích cực

- Một ngôn ngữ, một tiến trình, một lệnh chạy; không cần build frontend.
- `app.test_client()` cho phép test cả HTML lẫn JSON mà không cần dịch vụ ngoài.
- Mọi request đi qua `app/gate.py`, nên bất biến bảo mật (Bearer, CSRF) áp dụng thống nhất.

### Đánh đổi / rủi ro

- Frontend và backend buộc phải deploy cùng nhau.
- Không scale riêng phần đọc/ghi; chấp nhận được ở quy mô bài tập.
- Route mới rất dễ vô tình bỏ qua guard — đã có test `test_A16` bắt trường hợp này.

### Việc phải làm kèm theo

- Route mới phải qua `@require_role` (nếu cần quyền) và không được nằm ngoài `gate`.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Django | Nhiều thứ đi kèm (ORM, admin, migration) không cần, thời gian học lâu hơn |
| FastAPI + React | Hai repo, hai pipeline, CSRF/cookie phức tạp hơn nhiều so với nhu cầu |
| Node/Express | Đổi ngôn ngữ giữa chừng, không tận dụng được code Python đã có |
