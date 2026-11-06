# 0010 — Khoá tài khoản bằng cờ `locked`, token cũ 401 và login 429

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/admin.py`, `app/admin_service.py`, `app/auth.py`, ADR [0008](0008-token-vo-hieu-theo-giay.md)

## Bối cảnh

Bước 3.3 yêu cầu admin khoá/mở khoá tài khoản. Đề quy định rõ: token cũ của user bị khoá phải
trả `401 UNAUTHENTICATED`, còn login phải trả `429 ACCOUNT_LOCKED`. Cần phân biệt "user bị
khoá" với "token hết hạn" và với "sai mật khẩu quá 5 lần" (cũng 429 nhưng tạm thời 15 phút).

## Quyết định

- Thêm cột `users.locked` (0/1) và cache `state["locked"]`, nạp lại mỗi request như `bios`.
- `verify_token` từ chối user đang bị khoá → **401 UNAUTHENTICATED** (mọi request, kể cả token
  vừa phát).
- `_authenticate_user` kiểm tra `locked` **trước** khi so mật khẩu → **429 ACCOUNT_LOCKED**,
  kể cả khi mật khẩu đúng.
- Khoá/mở khoá: `POST /admin/users/<id>/lock|unlock`, chỉ ADMIN; khoá cũng gọi
  `auth.invalidate_tokens` để token cũ chết hẳn sau khi mở khoá.
- Không cho admin tự khoá mình (400), không khoá admin cuối cùng (400), khoá lặp lại → 409.
- `GET /admin/audit?limit=N` trả mảng JSON các dòng audit gần nhất (mặc định 100, 1..1000),
  chỉ ADMIN.

## Hệ quả

### Tích cực

- Ba trạng thái tách bạch: hết hạn token (401), bị khoá (401 + login 429), brute-force (429 tạm thời).
- Dữ liệu của user bị khoá (điểm, ghi danh) giữ nguyên; mở khoá là dùng lại được.
- Audit đọc được qua API, không cần truy cập file trên server.

### Đánh đổi / rủi ro

- 429 khi login cho tài khoản bị khoá **tiết lộ email tồn tại**; chấp nhận vì đề yêu cầu mã này.
- Audit trả nguyên văn bản ghi; nếu sau này log chứa dữ liệu nhạy cảm thì endpoint thành rò rỉ —
  phải giữ nguyên tắc "audit không chứa mật khẩu/token".
- Cờ `locked` nằm trong DB nên sống sót qua restart (khác `tokens_valid_after`).

### Việc phải làm kèm theo

- Mọi thay đổi `locked` phải qua `store.set_user_locked` + audit.
- Nếu thêm loại khoá mới (ví dụ khoá theo môn), phải ghi ADR mới.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Chỉ dùng `tokens_valid_after` khi khoá | Login vẫn phải chặn riêng; không phân biệt khoá với hết hạn |
| Xoá user khi khoá | Mất dữ liệu điểm/ghi danh, không mở khoá được |
| Trả 403 thay 429 khi login | Sai hợp đồng đề bài |
