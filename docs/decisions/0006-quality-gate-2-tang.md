# 0006 — Quality gate hai tầng: pre-commit nhanh + CI đầy đủ

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `.pre-commit-config.yaml`, `scripts/gate.ps1`, `.github/workflows/ci.yml`

## Bối cảnh

Cần chặn code lỗi trước khi merge nhưng không được làm chậm vòng lặp code. Chạy full
test (~100s) ở mỗi lần commit là quá chậm; ngược lại, chỉ chạy ở CI thì phản hồi muộn
và dễ push code hỏng. Repo đã có sẵn Semgrep trên GitHub Actions.

## Quyết định

**Tầng 1 — pre-commit (mục tiêu < 10s):** trailing whitespace, end-of-file, check YAML/TOML,
merge conflict, file lớn, `detect-private-key`, `ruff --fix`, `ruff-format`.

**Tầng 2 — `scripts/gate.ps1` + CI (đầy đủ):**

1. `ruff format --check .`
2. `ruff check .`
3. `mypy app`
4. `pytest --cov=app --cov-fail-under=80`
5. `pip-audit -r requirements.txt`
6. `semgrep` (local nếu có; CI chạy qua `semgrep.yml`)
7. `gitleaks` (CI, job security)

CI gồm job `quality` → `test` (Python 3.11/3.12/3.13) và `security`. PR chỉ merge khi
tất cả xanh.

## Hệ quả

### Tích cực

- Lỗi format/import bị bắt ngay khi commit, không tốn lượt CI.
- Test và coverage là điều kiện merge, không phải "chạy cho có".
- Quét secret hai lớp: `detect-private-key` (local) và `gitleaks` (CI, toàn bộ file).

### Đánh đổi / rủi ro

- Pre-commit không chạy test → lỗi logic chỉ lộ ở gate/CI (chấp nhận để giữ tốc độ).
- CI nhân 3 phiên bản Python làm thời gian phản hồi lâu hơn.
- `gitleaks` chạy bằng Docker image `latest` → cần ghim tag nếu muốn tái lập tuyệt đối.

### Việc phải làm kèm theo

- Cài hook: `pre-commit install` (một lần cho mỗi clone).
- Không dùng `git commit --no-verify` để né hook; nếu bí, sửa nguyên nhân.
- Chưa chạy gate và chưa xanh thì không được báo hoàn thành.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Chỉ dùng CI | Phản hồi chậm, push code hỏng liên tục |
| Chỉ dùng pre-commit | Máy khác nhau, có thể bị bỏ qua bằng `--no-verify` |
| Chạy full test ở pre-commit | ~100s mỗi commit, làm mất thói quen commit nhỏ |
| Husky/lint-staged | Dành cho Node, không phù hợp repo Python |
