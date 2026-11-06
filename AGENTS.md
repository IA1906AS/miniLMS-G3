# AGENTS.md — luật làm việc trong repository này

Đọc file này **đầu tiên**. Repo là nguồn ngữ cảnh duy nhất: không có ký ức giữa các phiên,
nên mọi thứ cần biết phải nằm trong file, không nằm trong đầu ai.

## 0. Phải đọc trước khi sửa bất cứ thứ gì

1. `README.md` — dự án làm gì, kiến trúc, cách chạy/test, trạng thái hiện tại.
2. `AGENTS.md` — file này.
3. `docs/conventions.md` — đặt tên, xử lý lỗi, test, commit.
4. ADR liên quan trong `docs/decisions/` (quyết định công nghệ, pattern đã chọn).
5. Code liên quan — đọc trước khi sửa, không đoán nội dung file.

## 1. Quy trình bắt buộc cho mỗi yêu cầu

1. **Nhắc lại yêu cầu + nêu giả định** bằng 2–3 dòng trước khi làm.
2. **Hỏi nếu mơ hồ.** Không tự chọn hành vi nghiệp vụ, schema, hay thư viện khi chưa rõ.
3. **Việc lớn → đưa kế hoạch và chờ duyệt.** Việc lớn là: thêm bảng/module, đổi API công khai,
   đổi cấu hình, thêm dependency, refactor lan rộng. Kế hoạch gồm file sẽ sửa và thứ tự làm.
4. **Code từng bước nhỏ, kèm test.** Mỗi bước phải chạy được; không gộp 3 việc vào 1 commit.
5. **Chạy quality gate** (mục 3). Đỏ thì sửa, không báo hoàn thành.
6. **Cập nhật README/ADR** nếu hành vi hoặc quyết định thay đổi.
7. **Báo cáo ngắn**: đã làm gì, test nào chứng minh, còn gì chưa làm.

## 2. Lệnh thường dùng (Windows PowerShell)

| Mục đích | Lệnh |
|---|---|
| Cài đặt | `python -m pip install -r requirements-dev.txt` |
| Chạy app | `$env:JWT_SECRET="..."; flask --app app run` |
| Test nhanh | `python -m pytest -q` |
| Test 1 file | `python -m pytest tests/test_outbox.py -q` |
| Coverage | `python -m pytest -q --cov=app --cov-report=term-missing` |
| Format | `python -m ruff format .` |
| Lint | `python -m ruff check .` |
| Type | `python -m mypy app` |
| Gate đầy đủ | `powershell -File scripts/gate.ps1` |
| Cài hook | `pre-commit install` |
| Outbox | `flask --app app outbox drain` / `... outbox status` |
| Bảo mật | `semgrep scan --config p/python --config p/flask --error --metrics=off` |

## 3. Quality gate — điều kiện bắt buộc

Gate gồm: `ruff format --check`, `ruff check`, `mypy app`, `pytest` với coverage ≥ 80%,
`pip-audit`, semgrep (nếu có), gitleaks ở CI.

> **Chưa chạy gate và chưa xanh thì không được báo hoàn thành.**
> Không dùng `--no-verify`, không `skip`/`xfail` test để né gate, không hạ `--cov-fail-under`.

## 4. KHÔNG được làm

- **Không tự thêm dependency.** Muốn thêm thì nêu lý do, chờ duyệt, cập nhật
  `requirements.txt`/`requirements-dev.txt` và ghi ADR nếu là quyết định công nghệ.
- **Không sửa ngoài phạm vi yêu cầu.** Thấy vấn đề khác thì ghi lại và báo, đừng sửa kèm.
- **Không bỏ qua test** hoặc xoá test đang đỏ để gate xanh.
- **Không commit secret:** `.env`, khoá thật, token, `*.sqlite3`, `audit.log`, `.venv/`.
- **Không sửa ADR cũ.** Quyết định đổi → tạo ADR mới + đánh dấu ADR cũ `Bị thay thế bởi 000X`.
- **Không đổi schema/API công khai** mà không cập nhật README + test + ADR.
- **Không gọi mạng/SMTP thật trong test.** Dùng `MAIL_TRANSPORT` hoặc monkeypatch.
- **Không viết SQL ngoài `app/store.py`**; không bỏ qua `CHECK`/transaction khi ghi dữ liệu.
- **Không log** mật khẩu, token, header `Authorization`, hay nội dung email.

## 5. Định nghĩa "hoàn thành"

- Code + test mới chạy xanh; coverage không giảm dưới 80%.
- `powershell -File scripts/gate.ps1` xanh (hoặc ghi rõ phần không chạy được và vì sao).
- README cập nhật nếu hành vi/trạng thái thay đổi; ADR mới nếu có quyết định mới.
- Commit theo Conventional Commits, một mục đích, không lẫn file rác.
