# 0008 — Mốc vô hiệu token tính theo giây (thay mục 5 của ADR 0007)

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/auth.py`, [0007](0007-giai-doan-3-phan-quyen.md) (bị thay thế một phần)

## Bối cảnh

ADR 0007 lưu `tokens_valid_after` dạng số thực và nâng `iat` thêm 1 giây khi phát token
ngay sau logout, kèm `verify_iat = False`. Cách đó làm token phát trong cùng giây bị từ
chối, trái với hợp đồng GĐ3: "token cấp ở giây hiện tại sau khi đổi vẫn hợp lệ".

## Quyết định

- `tokens_valid_after[user] = int(clock())` — mốc là **giây**, không phải số thực.
- `verify_token` từ chối khi `iat < tokens_valid_after` (so sánh số nguyên). Token phát ở
  đúng giây của mốc vẫn hợp lệ; token phát ở giây trước đó bị 401.
- Bỏ phần nâng `iat` khi đăng nhập và bỏ `verify_iat = False`: `iat = int(now)`, PyJWT
  kiểm tra `iat`/`exp` mặc định.
- Logout, đổi mật khẩu, đổi vai trò, khoá tài khoản (bước sau) đều gọi `invalidate_tokens`.

## Hệ quả

### Tích cực

- Đúng hợp đồng: không còn trường hợp đăng nhập lại ngay sau logout bị 401 oan.
- `iat` không bao giờ ở tương lai, nên bật lại kiểm tra `iat` của PyJWT an toàn.

### Đánh đổi / rủi ro

- Token phát trong cùng giây với logout vẫn dùng được tối đa 1 giây — đúng theo yêu cầu,
  nhưng là cửa sổ nhỏ cần ghi rõ trong báo cáo.
- Test phải vượt qua ranh giới giây (sleep ~1,05s) nếu muốn kiểm tra token bị vô hiệu.

### Việc phải làm kèm theo

- Không dùng `CLOCK` lùi/tiến cho test có xác minh JWT (PyJWT so `iat` với giờ thật).
- Mọi thao tác làm mất hiệu lực phiên phải gọi `auth.invalidate_tokens`, không tự set mốc.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Giữ số thực + nâng iat + tắt verify_iat | Token cùng giây bị 401, trái hợp đồng |
| Blacklist theo chuỗi token | Không dùng `tokens_valid_after` như đề yêu cầu |
| Chờ sang giây kế tiếp khi login | Không chấp nhận được về hành vi |
