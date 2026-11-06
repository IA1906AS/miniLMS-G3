# 0005 — Transactional outbox cho email xác nhận đăng ký

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/outbox.py`, `app/store.py`, `tests/test_outbox.py`

## Bối cảnh

Đăng ký khóa học cần hai việc: ghi `enrollments` và gửi email xác nhận. SQLite và SMTP
là hai hệ thống không chung transaction. Nếu gửi mail ngay trong request, SMTP lỗi sẽ
làm mất thông báo dù đăng ký đã lưu; nếu gửi trước khi commit, có thể gửi mail cho một
đăng ký bị rollback. Đây là pattern #8 trong bài tập.

## Quyết định

- Ghi **cả `enrollments` và `outbox_events(PENDING)` trong một transaction**
  (`store.create_enrollment`), không I/O mạng bên trong transaction.
- Dispatcher `outbox.drain_once()` claim batch bằng một transaction `BEGIN IMMEDIATE`,
  gửi ngoài transaction, rồi đánh `SENT` hoặc `PENDING`/`DEAD`.
- Giao nhận **at-least-once**; chống trùng phía nhận bằng `Message-ID: <eventId@lms.local>`.
- Retry dùng **delay cố định** (`OUTBOX_RETRY_DELAY_SECONDS`, mặc định 2s), không
  exponential backoff + jitter — đó là pattern #1, phải tách riêng.
- Event `SENDING` quá `OUTBOX_LEASE_SECONDS` được trả về `PENDING` để khôi phục sau crash.

## Hệ quả

### Tích cực

- Không mất sự kiện: đăng ký và event hoặc cùng tồn tại, hoặc cùng biến mất.
- Có thể demo lỗi SMTP mà dữ liệu vẫn đúng; `flask outbox drain` gửi lại được.
- Event nằm trong DB nên sống sót qua restart tiến trình (đã có test).
- Có trạng thái `DEAD` + `last_error` để điều tra thay vì retry vô hạn.

### Đánh đổi / rủi ro

- Email có thể bị gửi trùng (at-least-once); chấp nhận và ghi rõ trong README.
- Thêm một bảng và một module; cần chạy dispatcher (CLI hoặc worker nền).
- Nếu không ai chạy dispatcher, email sẽ nằm chờ — cần giám sát `flask outbox status`.

### Việc phải làm kèm theo

- Mọi sự kiện mới phải đi qua `outbox.new_event` + `store.create_enrollment` (hoặc hàm
  ghi transaction tương đương), không gọi emailer trực tiếp trong request.
- Giữ `payload` là JSON thuần, không chứa mật khẩu/token.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Gửi mail ngay trong request | SMTP lỗi làm mất thông báo; không retry được |
| Gửi trước, commit sau | Có thể gửi mail cho đăng ký bị rollback |
| Celery/Redis queue | Thêm hạ tầng, vượt phạm vi "1 module + 1 bảng" |
| Backoff + jitter ngay trong outbox | Trùng pattern #1 của bài tập, khó tách vai trò |
