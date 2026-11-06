# 0002 — SQLite + SQL thuần, không ORM

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS

## Bối cảnh

Dữ liệu nhỏ (vài bảng, vài chục dòng), nhưng có nhiều chỗ cần kiểm soát transaction
chính xác: reset mật khẩu (token dùng một lần), cập nhật điểm, và outbox cho email
xác nhận đăng ký. Bài tập cũng yêu cầu tự cài đặt logic (ví dụ claim batch của outbox),
nên SQL cần nhìn thấy được thay vì bị ORM che.

## Quyết định

Dùng **`sqlite3` của thư viện chuẩn**, toàn bộ SQL tập trung trong `app/store.py`:

- `isolation_level=None` + `BEGIN IMMEDIATE` cho các giao dịch ghi.
- Một `RLock` (`state["lock"]`) bảo vệ truy cập đồng thời trong tiến trình.
- Đọc dữ liệu nóng qua cache trong `state`, làm mới bằng `store.refresh()` mỗi request
  (gọi từ `app/gate.py`).
- Không thêm migration framework; thay đổi schema dùng `CREATE TABLE IF NOT EXISTS` và
  `ALTER TABLE` có kiểm tra.

## Hệ quả

### Tích cực

- Transaction và khóa hiện rõ; dễ viết câu `UPDATE ... WHERE version = ?` cho pattern
  optimistic locking sau này.
- Không thêm dependency, test chạy được với database `:memory:`.
- Dễ giải thích trong báo cáo: mỗi thao tác ghi là một khối SQL nhìn thấy được.

### Đánh đổi / rủi ro

- SQL viết tay, không có ORM sinh query; đổi schema phải sửa cả `init()` và `refresh()`.
- SQLite chỉ một writer tại một thời điểm; chấp nhận được ở quy mô bài tập.
- Cache trong RAM bắt buộc phải refresh đúng, nếu không sẽ trả dữ liệu cũ.

### Việc phải làm kèm theo

- Mọi hàm ghi mới phải nằm trong `store.py`, bọc `BEGIN IMMEDIATE` + `ROLLBACK` khi lỗi.
- Cột mới phải được thêm vào cả `CREATE TABLE` và câu `SELECT` trong `refresh()`.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| SQLAlchemy ORM | Thêm dependency, che transaction — đúng phần bài tập cần tự viết |
| PostgreSQL | Cần hạ tầng/Docker, không cần thiết cho quy mô này |
| JSON file | Không có transaction, dễ mất dữ liệu khi ghi đồng thời |
