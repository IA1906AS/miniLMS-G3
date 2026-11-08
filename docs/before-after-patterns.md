# Before / After — Pattern #3 (Optimistic locking) và #8 (Transactional outbox)

Tài liệu này giải thích hai nhánh của bài tập defensive pattern:

| Nhánh | Nội dung |
|---|---|
| `feature/before` | Bản **chưa vá**: tái hiện đúng hai rủi ro của pattern #3 và #8. |
| `main` | Bản **đã vá**: optimistic locking cho sửa điểm + transactional outbox cho email đăng ký. |

## 1. Pattern #3 — Optimistic locking cho tính năng "Sửa điểm"

**Rủi ro (theo đề bài):** người lưu sau ghi đè thay đổi của người trước (lost update).

Kịch bản: hai giảng viên (hoặc hai tab) cùng mở bảng điểm của `u4` trong khóa `c1`:

```
T1: A đọc điểm u4 = 7.5
T2: B đọc điểm u4 = 7.5
T3: A lưu 8.0  -> DB = 8.0
T4: B lưu 9.0  -> DB = 9.0   (mất thay đổi của A, không ai biết)
```

### Bản Before (`feature/before`)

- `PUT /courses/<id>/grades/<sid>` chỉ là `UPDATE enrollments SET score = ?` — ghi đè vô điều kiện.
- Không có cột `version`, không có endpoint `/v2`, không có mã `409 CONFLICT`.
- Chứng minh: `tests/test_grade_lost_update.py`.

### Bản After (`main`)

- Thêm cột `enrollments.version` (có `ALTER TABLE` cho DB cũ).
- `GET /courses/<id>/grades/<sid>/v2` trả `version`.
- `PUT .../v2` bắt buộc `expectedVersion`; câu `UPDATE ... WHERE ... AND version = ?` nằm trong
  `BEGIN IMMEDIATE`, `rowcount = 0` → `409 CONFLICT` (phân biệt 404 và 409 trong cùng transaction).
- Chứng minh: `tests/test_grade_version.py`; quyết định ghi ở `docs/decisions/0013-optimistic-locking-diem.md`.

## 2. Pattern #8 — Transactional outbox cho "Email xác nhận đăng ký khóa học"

**Rủi ro (theo đề bài):** dữ liệu đã lưu nhưng sự kiện (email) bị mất.

Đăng ký khóa học cần hai việc ở hai hệ thống khác nhau (PostgreSQL và SMTP). Không có transaction
chung, nên nếu gửi mail ngay trong request:

```python
store.add_enrollment(...)      # đã commit
emailer.send_email(...)        # SMTP chết -> sinh viên đã vào lớp nhưng không có mail
```

### Bản Before (`feature/before`)

- `services.enroll_in_course` ghi `enrollments` rồi gọi `emailer.send_email` ngay.
- SMTP lỗi → request nổ **sau khi** dữ liệu đã commit: email mất, không retry, đăng ký lại thì
  bị `409` vì đã ghi danh.
- Chứng minh: `tests/test_enrollment_email_before.py`
  (`test_smtp_failure_loses_email_but_keeps_enrollment`).

### Bản After (`main`)

- `store.create_enrollment` ghi `enrollments` **và** `outbox_events(PENDING)` trong **một**
  transaction, không I/O mạng bên trong transaction.
- `outbox.drain_once()` claim batch bằng một `UPDATE`, gửi ngoài transaction, đánh `SENT` hoặc
  trả về `PENDING`/`DEAD`; giao nhận at-least-once, chống trùng bằng `Message-ID`.
- Chứng minh: `tests/test_outbox.py`; quyết định ghi ở `docs/decisions/0005-outbox-email-dang-ky.md`.

## 3. Cách chạy thử

```powershell
# Bản Before: lỗi tái hiện được
git switch feature/before
python -m pytest tests/test_grade_lost_update.py tests/test_enrollment_email_before.py -q

# Bản After: đã vá
git switch main
python -m pytest tests/test_grade_version.py tests/test_outbox.py -q
```

Với API (After), sửa điểm có xung đột:

```bash
GET  /courses/c1/grades/u4/v2                      # -> version hiện tại
PUT  /courses/c1/grades/u4/v2  {"score": 8, "expectedVersion": 0}   # 200, version = 1
PUT  /courses/c1/grades/u4/v2  {"score": 9, "expectedVersion": 0}   # 409 CONFLICT
```

Với email (After), tắt SMTP rồi đăng ký: dữ liệu vẫn lưu, `outbox_events` có dòng `PENDING`;
bật SMTP và chạy `flask outbox drain` để gửi bù.

## 4. Ghi chú

- Bản Before chỉ gỡ hai pattern ở đúng tính năng của bài tập. Module `app/outbox.py` vẫn còn vì
  luồng thông báo lớp học (`announcement.posted`) dùng chung hạ tầng này.
- Các tài liệu `README.md`, `docs/decisions/0005-*`, `docs/decisions/0013-*` mô tả thiết kế của
  bản After (`main`).
