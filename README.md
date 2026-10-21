# LMS

Ứng dụng Flask có giao diện HTML và JSON API, sử dụng SQLite để lưu tài khoản,
khóa học, điểm và liên kết reset mật khẩu.

## Chạy ứng dụng

1. Cài dependency: `python -m pip install -r requirements.txt`.
2. Cấu hình biến môi trường theo [.env.example](./.env.example), đặc biệt:
   - `JWT_SECRET`: chuỗi ngẫu nhiên tối thiểu 32 ký tự.
   - `DATABASE_PATH`: đường dẫn file SQLite; mặc định `lms.sqlite3`.
   - `PUBLIC_BASE_URL`: origin công khai của website, dùng để tạo liên kết reset
     trong email; đặt thành HTTPS khi triển khai thật.
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM` và thông tin đăng nhập SMTP để gửi
     email reset mật khẩu.
3. Chạy: `flask --app app run`.

Ví dụ cấu hình nhanh trong PowerShell (thay bằng giá trị thật):

```powershell
$env:JWT_SECRET = "replace-with-a-random-secret-of-32-or-more-characters"
$env:SMTP_HOST = "smtp.example.com"
$env:SMTP_FROM = "noreply@example.com"
flask --app app run
```

Các trang chính: `/`, `/login`, `/register`, `/forgot-password`,
`/reset-password?token=...` và `/account`. Trang account yêu cầu đăng nhập.
Các trang xác thực dùng tài nguyên cùng nguồn trong
`app/static/css/auth.css` và `app/static/js/auth.js`. API JSON có
`POST /auth/login`, `POST /auth/register`, `POST /auth/forgot-password` và
`POST /auth/reset-password`; các đường dẫn reset cũ `/auth/password-reset` và
`/auth/password-reset/confirm` vẫn được giữ để tương thích.

Các request xác thực từ trình duyệt gửi CSRF token qua `X-CSRF-Token`. Đăng nhập
qua giao diện dùng cookie phiên `HttpOnly`, có thời hạn 30 ngày nếu chọn “Ghi
nhớ đăng nhập”. Đặt `SESSION_COOKIE_SECURE=true` khi chạy qua HTTPS; khi phát
triển trên HTTPS, đặt `PUBLIC_BASE_URL` thành origin HTTPS thực tế.

Để bật đăng nhập Google/GitHub, tạo OAuth app tại từng nhà cung cấp, thêm
callback URI tương ứng:

- `{PUBLIC_BASE_URL}/oauth/google/callback`
- `{PUBLIC_BASE_URL}/oauth/github/callback`

Sau đó cấu hình `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`
và `GITHUB_CLIENT_SECRET`. Không tự động liên kết một OAuth identity với tài
khoản MiniLMS cùng email; người dùng cần đăng nhập bằng tài khoản hiện có.

Database mới được khởi tạo từ `app/seed.json` để giữ dữ liệu khóa học mẫu và
tài khoản demo. Trước khi triển khai thật, thay thông tin tài khoản demo và
mật khẩu trong dữ liệu seed, bảo vệ cấu hình SMTP/secret, và chỉ chạy qua HTTPS.

## Kiểm thử

Chạy `python -m pytest -q`. Môi trường kiểm thử dùng SQLite trong bộ nhớ trừ khi
kiểm thử chỉ định rõ đường dẫn database riêng.
