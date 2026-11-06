# 0003 — pytest + coverage 80%

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS

## Bối cảnh

Cần bộ test hồi quy cho các bất biến bảo mật (401/403/404, CSRF, audit) và cho pattern
outbox (at-least-once, DEAD, khôi phục sau restart). Test phải chạy được trên Windows
lẫn CI Ubuntu, không phụ thuộc mạng hay SMTP thật.

## Quyết định

- Dùng **pytest** (`>=9.0,<10.0`) + **pytest-cov**; cấu hình trong `pyproject.toml`
  (`[tool.pytest.ini_options]`), bỏ `pytest.ini`.
- Đo coverage trên `app/`, bật `branch = true`, ngưỡng **80%** (`--cov-fail-under=80`).
- Test đặt trong `tests/`, mỗi file theo module/hành vi; dùng fixture `app` + `client`.
- Không gọi SMTP thật: bơm `MAIL_TRANSPORT` hoặc monkeypatch `app.emailer`.

## Hệ quả

### Tích cực

- 110 test, chạy ~100s trên máy local; coverage thực tế ~84% (margin ~4 điểm).
- Test được cả HTML (CSRF, form) và JSON API bằng cùng `test_client`.
- Bắt được hồi quy của pattern outbox: retry, DEAD, restart, lease.

### Đánh đổi / rủi ro

- Mỗi lần `create_app()` seed lại 6 user bằng bcrypt, nên test chậm hơn mức lý tưởng.
- Ngưỡng 80% là sàn, không phải mục tiêu: code mới vẫn phải có test hành vi.
- `schema` thay đổi dễ làm coverage tụt nếu không thêm test tương ứng.

### Việc phải làm kèm theo

- Thêm test trước hoặc cùng lúc với code; không dùng `skip`/`xfail` để né gate.
- Nếu coverage tụt dưới 80%, bổ sung test chứ không hạ ngưỡng (muốn hạ thì tạo ADR mới).

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| `unittest` thuần | Fixture và parametrize kém linh hoạt hơn |
| pytest 8.4.2 (bản cũ) | Có cảnh báo bảo mật PYSEC-2026-1845; bản vá nằm ở 9.0.3 |
| Không đo coverage | Không phát hiện được phần code chết/không được kiểm chứng |
| Ngưỡng 90% | Phần `oauth.py` gọi mạng thật khó test, dễ dẫn tới test hình thức |
