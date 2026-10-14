# myapp

Project Python quản lý bằng [uv](https://docs.astral.sh/uv/).

```bash
uv sync          # tạo .venv và cài đúng phiên bản trong uv.lock
uv run main.py   # chạy app
uv run pytest    # chạy test
uv run ruff check .
uv add <package> # thêm dependency
```

## Kiểm tra chất lượng code (1 lệnh)

Trước khi commit, chạy script `check.ps1` để kiểm tra toàn bộ:

```powershell
.\check.ps1
```

Script sẽ chạy lần lượt **ruff (lint + format) → mypy → pytest (+coverage) → pip-audit**
và in ra bảng tổng kết PASS/FAIL.

## pre-commit (tự chạy kiểm tra mỗi lần commit)

Dự án đã cấu hình `.pre-commit-config.yaml` để tự chạy **ruff check → ruff format → mypy**
trước mỗi `git commit`. Cài hook (chỉ làm 1 lần sau khi `git init`):

```powershell
uv run pre-commit install
uv run pre-commit run --all-files   # chạy thử trên toàn bộ file
```

Nếu code có lỗi, commit sẽ bị **tự động chặn** cho tới khi bạn sửa xong.

## CI - GitHub Actions

File `.github/workflows/ci.yml` sẽ tự động chạy toàn bộ kiểm tra
(**ruff → ruff format → mypy → pytest → pip-audit**) trên máy chủ GitHub
mỗi khi bạn `git push` hoặc mở Pull Request. Xem kết quả ở tab **Actions** trên repo.


