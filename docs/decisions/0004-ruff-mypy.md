# 0004 — Ruff (format + lint) và mypy mức cơ bản

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS

## Bối cảnh

Repo chưa có formatter/linter, code do 2 người viết nên dễ lệch style và lọt import thừa.
Cần bộ công cụ chạy nhanh trên Windows, không cần cài môi trường phức tạp, và không tạo
ra hàng trăm cảnh báo khiến người mới bỏ qua gate.

## Quyết định

- **Ruff** cho cả format và lint: line-length 100, target `py311`, bộ luật
  `E, F, W, I, B, UP, SIM`.
- **mypy** mức cơ bản: chỉ `app/`, `check_untyped_defs = true`,
  `ignore_missing_imports = true`, chưa bật `strict`.
- Chạy qua **pre-commit** (tầng nhanh) và CI/`scripts/gate.ps1` (tầng đầy đủ).

## Hệ quả

### Tích cực

- Một lần chạy `ruff format` chuẩn hóa toàn repo (14 file), diff chủ yếu là khoảng trắng.
- Ruff thay được black + flake8 + isort, giảm 3 dependency xuống 1.
- mypy bắt được lỗi thật ngay lần đầu: `HTTPException.code` có thể `None`
  (`app/errors.py`), đã sửa.

### Đánh đổi / rủi ro

- Đã reformat toàn bộ code một lần → commit lớn, cần merge cẩn thận nếu có nhánh khác.
- mypy cơ bản chưa bắt được nhiều lỗi kiểu (dict `Any` khắp nơi); muốn strict phải
  gõ kiểu dần và tạo ADR mới.
- `ignore_missing_imports = true` che lỗi thiếu stub của Flask/bcrypt.

### Việc phải làm kèm theo

- Không tắt luật bằng `# noqa` hàng loạt; chỉ dùng khi có lý do ghi ngay bên cạnh.
- Chạy `ruff format` trước khi commit để pre-commit không phải sửa file.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| black + flake8 + isort | Ba công cụ, ba cấu hình, chậm hơn |
| mypy `strict` | Hàng trăm lỗi do dict/Flask, không kịp tiến độ |
| Chỉ dựa vào semgrep | Semgrep bắt bảo mật, không bắt style/import/type |
| Không có linter | Hai người viết sẽ lệch style, review tốn thời gian |
