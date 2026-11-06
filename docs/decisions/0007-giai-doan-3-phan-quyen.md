# 0007 — Phân quyền mở rộng (GĐ3) và các khác biệt so với đề Defense-in-Depth

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/extended.py`, `app/auth.py`, ADR [0002](0002-sqlite-raw-sql.md), [0005](0005-outbox-email-dang-ky.md)

## Bối cảnh

Đề "Defense in Depth" yêu cầu dữ liệu chỉ nằm trong bộ nhớ, allowlist của gate chỉ có
`POST /auth/login`, và GĐ3 bổ sung 8 endpoint phân quyền. Repo hiện tại đã hoàn thành
GĐ1–GĐ2 nhưng có ba khác biệt: dùng SQLite, allowlist có thêm route tự phục vụ
(đăng ký/reset/OAuth), và đang dùng `POST /courses/<id>/enrollments` cho sinh viên tự
đăng ký (pattern #8).

## Quyết định

1. **Giữ SQLite** theo ADR 0002. `create_app()` vẫn tạo state mới và nạp lại seed mỗi lần;
   khác biệt "không dùng database" được ghi nhận là có chủ đích, không sửa trong GĐ3.
2. **Giữ allowlist mở rộng cho các route tự phục vụ** (`/auth/register`,
   `/auth/password-reset`, `/auth/reset-password`, `/oauth/*` đã nằm ngoài gate qua
   blueprint `web`). Gate vẫn **mặc định từ chối**: route mới không khai báo gì sẽ 401.
   Không thêm bất kỳ endpoint GĐ3 nào vào allowlist.
3. **GĐ3 nằm trong blueprint riêng** `app/extended.py`; không sửa hành vi 4 endpoint lõi
   (`/auth/login`, `/me`, `GET|PUT .../grades`).
4. **Nhường path ghi danh**: sinh viên tự đăng ký chuyển sang `POST /me/enrollments`
   (`{"courseId": ...}`, có outbox); `POST /courses/<id>/enrollments` (`{"studentId": ...}`)
   thuộc về ADMIN/INSTRUCTOR như đề GĐ3 quy định. Không còn hai nghĩa trên một URL.
5. **Vô hiệu token bằng mốc thời gian**: lưu `tokens_valid_after[user]`; token có
   `iat < mốc` bị 401. Logout và đổi vai trò đều cập nhật mốc. Khi phát token ngay sau
   logout, `iat` được nâng lên `int(mốc) + 1` và `verify_token` tắt `verify_iat`
   (`exp` vẫn kiểm tra) để tránh lỗi "token chưa hợp lệ" trong cùng một giây.

## Hệ quả

### Tích cực

- Không phá pattern #8 và các tính năng đã có; GĐ3 cô lập, dễ revert.
- Không có hai endpoint trùng URL với hai hợp đồng khác nhau.
- Token cũ mất hiệu lực ngay sau logout/đổi quyền, kể cả trong cùng giây.

### Đánh đổi / rủi ro

- Bài nộp lệch 1 ràng buộc của đề (SQLite thay vì in-memory) — cần nêu khi bảo vệ.
- `verify_iat=False` chấp nhận token có `iat` nhích tới 1 giây trong tương lai; không mở
  đường giả mạo vì chữ ký vẫn bắt buộc.
- `tokens_valid_after` chỉ nằm trong RAM: restart tiến trình sẽ "hồi sinh" token cũ cho tới
  khi hết `exp`. Chấp nhận ở quy mô bài tập; nếu cần bền thì thêm cột vào `users`.

### Việc phải làm kèm theo

- Endpoint mới phải dùng `store_scope` + `require_role` + service kiểm tra lại quyền.
- Ghi audit cho mọi thay đổi ghi danh/vai trò.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Bỏ SQLite, chuyển in-memory đúng đề | Phá outbox (#8) và toàn bộ test hiện có |
| Giữ 1 URL `/courses/<id>/enrollments` cho cả hai luồng | Hai hợp đồng chồng nhau, dễ 403/400 sai thứ tự |
| Blacklist token theo chuỗi | Không theo đúng thiết kế `tokens_valid_after` của đề |
| Chờ sang giây kế tiếp khi login | Không chấp nhận được về mặt hành vi |
