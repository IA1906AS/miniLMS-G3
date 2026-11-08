# Đề xuất 2 defensive pattern cho MiniLMS

Tài liệu chọn 2 trong 10 pattern của bài tập, gắn trực tiếp với mã nguồn hiện có trong repo, và
mô tả cách cài đặt + cách nghiệm thu. Bản cập nhật này bám theo PostgreSQL (psycopg 3) và ghi nhận
trạng thái triển khai thực tế của cả hai pattern.

**Lịch sử cập nhật:** 08/11/2026 — chuyển toàn bộ ví dụ sang PostgreSQL; cập nhật trạng thái #3
đã cài đặt; sửa đường dẫn module và số liệu kiểm thử.

## 1. Kết luận nhanh

| Thành viên | Pattern | Tính năng LMS | Module mới | Bảng mới | Trạng thái |
|---|---|---|---|---|---|
| A | **#3 Optimistic locking** | Sửa điểm | `app/grades_v2.py`, `app/grade_version_service.py` | không (thêm cột `version` vào `enrollments`) | Đã cài đặt |
| B | **#8 Transactional outbox** | Email xác nhận đăng ký khóa học | `app/outbox.py` | `outbox_events` | Đã cài đặt |

Lý do chọn cặp này:

- Cả hai đều nằm trên miền dữ liệu **đã có** trong repo (`enrollments`, `emailer`), nên không phải
  dựng thêm một tính năng lớn chỉ để có chỗ gắn pattern.
- Hai rủi ro khác nhau về bản chất: #3 là **tính đúng đắn khi ghi đồng thời** (lost update), #8 là
  **tính bền của sự kiện khi có hai lần ghi** (dual-write). Không trùng lặp ý tưởng, thuyết trình
  được hai góc nhìn bổ sung cho nhau.
- Cả hai đều **test được bằng pytest** và **demo được trong 5 phút**.
- Mỗi pattern nằm trong phạm vi cho phép: #3 chỉ thêm **một cột**, #8 thêm **một module + một bảng**.

## 2. Hiện trạng repo (căn cứ để chọn)

Ứng dụng Flask 3 + PostgreSQL, không ORM, dùng SQL thuần qua `psycopg` 3; mọi thao tác ghi nằm
trong transaction tường minh (`BEGIN`/`COMMIT`) trên connection `autocommit=True`.

| Thành phần | Vị trí | Ghi chú liên quan |
|---|---|---|
| Cơ sở dữ liệu | PostgreSQL 18 (dev) | DSN lấy từ `DATABASE_URL`; giá trị mặc định trong code dùng cổng 2010, còn PostgreSQL cài local thường ở 5432 — kiểm tra và đặt lại khi chạy |
| Bảng dữ liệu | `app/store.py` | `users`, `courses`, `enrollments(course_id, student_id, score, version)`, `password_reset_tokens`, `oauth_accounts`, `outbox_events`, và các bảng bài tập/quiz/diễn đàn |
| Sửa điểm (endpoint lõi) | `store.update_grade` | Ghi đè kiểu last-write-wins nhưng **tăng `version`** sau mỗi lần ghi |
| Sửa điểm (endpoint v2) | `grade_version_service.update_grade` → `store.update_grade_if_version` | So khớp `version` bằng một câu `UPDATE` có điều kiện; lệch → 409 |
| Đọc điểm | `GET /courses/<id>/grades` và `GET .../v2` | Endpoint lõi không trả version; endpoint v2 trả `version` |
| Gửi mail | `app/emailer.py` | SMTP; ném `RuntimeError` nếu thiếu `SMTP_HOST`/`SMTP_FROM` |
| Nạp lại cache | `app/gate.py::_gate` gọi `store.refresh(state)` mỗi request | Cache chỉ giữ `score`; `version` đọc trực tiếp từ DB |
| Lỗi | `app/errors.py` | `AppError` → JSON `{"error": "<CODE>"}`; v2 dùng `Conflict` (409) |
| Kiểm thử | `tests/` | 299 test được thu thập tại thời điểm cập nhật; 19 test cho optimistic locking, 15 test cho outbox |
| Worker outbox | `app/outbox.py::start_worker` | Tuỳ chọn, bật bằng `OUTBOX_POLL_INTERVAL > 0`; tắt khi `TESTING` |

Lưu ý: vì `store.refresh` chạy mỗi request, các cột mới thêm vào bảng phải được cân nhắc khi đọc
cache. Riêng `version` **không** nằm trong cache `state["enrollments"]`; nó được đọc bằng
`store.read_grade_version` để tránh sai lệch giữa cache và DB.

## 3. Vì sao không chọn các pattern còn lại

| # | Pattern | Đánh giá cho repo này |
|---|---|---|
| 1 | Exponential backoff + jitter (email điểm) | Outbox hiện dùng **retry cố định** `OUTBOX_RETRY_DELAY_SECONDS`; thêm backoff/jitter sẽ trộn #1 vào #8. Repo cũng chưa có email thông báo điểm. |
| 2 | Idempotency key (nộp bài tập) | Đã có bài nộp và cơ chế trả lại bài cũ khi nộp trùng nội dung, nhưng chưa có khoá idempotency do client gửi; thêm bảng khoá + header sẽ vượt phạm vi "tối đa một bảng". |
| 3 | Optimistic locking (sửa điểm) | **Đã chọn** — xem mục 4. |
| 4 | Token bucket (trợ lý AI) | Repo không có AI assistant; phải giả lập dịch vụ ngoài. |
| 5 | Circuit breaker (kiểm tra đạo văn) | Không có dịch vụ ngoài nào để bảo vệ. |
| 6 | Timeout + fallback (dashboard) | Không có dashboard; chỉ có timeout rời rạc ở SMTP (15 giây) và OAuth (12 giây), không có fallback. |
| 7 | Máy trạng thái (lượt làm bài) | Đã có `quiz_attempts` với `started_at`/`submitted_at`, chặn nộp lại và chặn quá hạn, nhưng chưa có cột `state` + bảng chuyển trạng thái tường minh; nếu chọn phải mở rộng schema. |
| 8 | Transactional outbox (email đăng ký) | **Đã chọn** — xem mục 5. |
| 9 | Bulkhead (xuất báo cáo điểm) | Chưa có chức năng xuất báo cáo; thêm thread pool/semaphore lúc này là tạo tính năng mới. |
| 10 | Giữ chỗ có thời hạn (lớp giới hạn sĩ số) | Chưa có `capacity`/bảng giữ chỗ; tranh chấp ghi trên PostgreSQL có thể demo được nhưng vượt phạm vi một bảng. |

## 4. Pattern A — #3 Optimistic locking cho "Sửa điểm"

### 4.1. Rủi ro cần chứng minh

Hai giảng viên (hoặc 2 tab của cùng một người) cùng mở bảng điểm:

```
T1: A đọc điểm u4 = 7.5 (version 2)
T2: B đọc điểm u4 = 7.5 (version 2)
T3: A lưu 8.0   -> DB = 8.0
T4: B lưu 9.0   -> DB = 9.0   (mất thay đổi của A, không ai biết)
```

Endpoint lõi `PUT /courses/<id>/grades/<sid>` vẫn là last-write-wins. Endpoint v2 được thêm để
client có thể gửi kèm phiên bản đã đọc và bị từ chối nếu dữ liệu đã đổi.

### 4.2. Phạm vi

- Route: `app/grades_v2.py` — cặp `GET/PUT /courses/<course_id>/grades/<student_id>/v2`.
- Nghiệp vụ: `app/grade_version_service.py` — `get_grade`, `update_grade`; không import Flask.
- Dữ liệu: thêm **cột**, không thêm bảng:

```sql
ALTER TABLE enrollments ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
```

> Code hiện tại không thêm `updated_at`; nếu cần hiển thị "sửa lần cuối" thì đó là thay đổi schema
> riêng, không thuộc pattern này.

### 4.3. Hợp đồng HTTP

Đọc một điểm:

```
GET /courses/c1/grades/u4/v2
200 OK
{"courseId": "c1", "studentId": "u4", "score": 7.5, "version": 0}
```

Ghi điểm:

```
PUT /courses/c1/grades/u4/v2
{"score": 9, "expectedVersion": 0}
```

| Tình huống | Mã | Body |
|---|---|---|
| Thiếu hoặc sai `expectedVersion` | `400` | `{"error": "VALIDATION_ERROR"}` |
| Không có quyền / không phải GV phụ trách | `403` | `{"error": "FORBIDDEN"}` |
| Không có môn hoặc không có bản ghi điểm | `404` | `{"error": "NOT_FOUND"}` |
| Version cũ | `409` | `{"error": "CONFLICT"}` |
| Hợp lệ | `200` | `{"courseId": "c1", "studentId": "u4", "score": 9, "version": 1}` |

Khác với bản đề xuất ban đầu, implementation **không dùng `If-Match`/ETag** và trả **409** thay vì
412/428. Lý do được ghi ở [ADR 0013](decisions/0013-optimistic-locking-diem.md): giữ nguyên hợp
đồng của endpoint lõi và dùng body `{score, expectedVersion}` theo yêu cầu của đề bài.

### 4.4. Cài đặt cốt lõi

Điểm mấu chốt là **một câu UPDATE có điều kiện**, không phải đọc-rồi-ghi:

```python
cursor = connection.execute(
    """
    UPDATE enrollments
       SET score = %s, version = version + 1
     WHERE course_id = %s AND student_id = %s AND version = %s
    """,
    (score, course_id, student_id, expected_version),
)
if cursor.rowcount == 0:
    # Phân biệt "không tồn tại" và "version cũ" trong cùng transaction
    row = connection.execute(
        """
        SELECT score, version FROM enrollments
         WHERE course_id = %s AND student_id = %s
        """,
        (course_id, student_id),
    ).fetchone()
    connection.execute("ROLLBACK")
    if row is None:
        return False, None, None          # service đổi thành NotFound
    return False, int(row[1]), row[0]     # service đổi thành Conflict
```

Các điểm đã sửa cho khớp codebase:

1. `store.init`: thêm cột `version` vào `CREATE TABLE enrollments` (DB mới) và `ALTER TABLE` có
   kiểm tra `_table_columns` (DB cũ).
2. `store.update_grade` (endpoint lõi): vẫn last-write-wins nhưng tăng `version` để client v2 phát
   hiện được cả thay đổi do client cũ ghi.
3. `store.update_grade_if_version`: trả `(updated, new_version, current_score)`; dùng
   `cursor.rowcount` và `SELECT` trong cùng transaction để phân biệt 404 và 409.
4. `store.read_grade_version`: đọc `score, version` trực tiếp từ DB, không lấy từ cache.
5. `grade_version_service.update_grade`: kiểm tra quyền, validate điểm, gọi store, ghi audit
   `oldScore`, `newScore`, `version`.
6. `app/grades_v2.py`: route `GET/PUT` v2, vẫn qua `@require_role("INSTRUCTOR")` và `@store_scope`.
7. `app/errors.py`: dùng `Conflict` (409) sẵn có; không thêm 412/428.

### 4.5. Nghiệm thu

- [x] `GET .../v2` trả `version` ban đầu.
- [x] `PUT` đúng version → 200, `version` tăng 1.
- [x] `PUT` với version cũ → 409, DB giữ nguyên giá trị của lần ghi đầu.
- [x] Ghi qua endpoint lõi cũng tăng version, nên client v2 phát hiện được.
- [x] Hợp đồng endpoint lõi và `GET .../grades` không đổi.
- [x] GV khác môn / sinh viên → 403; môn hoặc bản ghi không tồn tại → 404.
- [x] Body sai (thiếu trường, `score` ngoài 0–10, `expectedVersion` âm/không phải int) → 400.
- [x] Audit ghi một dòng `UPDATE_GRADE` với `oldScore`, `newScore`, `version`.
- [x] Service kiểm tra lại quyền (không chỉ dựa vào route).
- [ ] **Chưa có** test 20 request song song cùng `expectedVersion`; nếu muốn chứng minh mạnh hơn
      thì thêm test dùng `ThreadPoolExecutor` + `app.test_client()` riêng cho mỗi thread.
- [ ] **Chưa có** test hai tiến trình/worker thật; hiện mới test ở tầng service và HTTP.

## 5. Pattern B — #8 Transactional outbox cho "Email xác nhận đăng ký khóa học"

### 5.1. Rủi ro cần chứng minh

Đăng ký khóa học cần 2 việc: ghi `enrollments` và gửi email xác nhận. Nếu viết thẳng:

```python
store.create_enrollment(...)   # đã commit
emailer.send_email(...)        # SMTP chết -> sinh viên đã vào lớp nhưng không có mail
```

hoặc gửi mail trước rồi commit thất bại → email "ma" cho một đăng ký không tồn tại. Đây là
**dual-write**: PostgreSQL và SMTP không nằm trong một transaction.

### 5.2. Phạm vi

- Tính năng: `POST /me/enrollments` (body `{"courseId": ...}`) — sinh viên tự đăng ký; form web
  `POST /courses/<id>/enroll`.
- Module mới: `app/outbox.py` — `new_event`, `build_message`, `drain_once`, `start_worker`.
- Bảng mới (đúng 1 bảng): `outbox_events`.
- Hàm ghi/đọc trong `app/store.py`: `create_enrollment`, `recover_expired_outbox`,
  `claim_outbox_batch`, `mark_outbox_sent`, `mark_outbox_failed`, `outbox_counts`.

### 5.3. Bảng dữ liệu (PostgreSQL)

```sql
CREATE TABLE IF NOT EXISTS outbox_events (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id        TEXT NOT NULL UNIQUE,       -- cũng dùng làm Message-ID
    type            TEXT NOT NULL,              -- 'enrollment.confirmed', 'announcement.posted'
    payload         TEXT NOT NULL,              -- JSON: course, student, email
    status          TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING|SENDING|SENT|DEAD
    attempts        INTEGER NOT NULL DEFAULT 0,
    next_attempt_at DOUBLE PRECISION NOT NULL,
    locked_until    DOUBLE PRECISION,
    created_at      DOUBLE PRECISION NOT NULL,
    sent_at         DOUBLE PRECISION,
    last_error      TEXT
);

CREATE INDEX IF NOT EXISTS idx_outbox_due
    ON outbox_events (status, next_attempt_at);
```

`event_id` sinh bằng `secrets.token_urlsafe(16)` **trong transaction**; `UNIQUE` đảm bảo không tạo
trùng nếu logic bị gọi lặp.

### 5.4. Luồng ghi (transaction duy nhất, không I/O)

```python
connection.execute("BEGIN")
try:
    connection.execute(
        "INSERT INTO enrollments (course_id, student_id, score) VALUES (%s, %s, %s)",
        (course_id, student_id, 0.0),
    )
    connection.execute(
        """
        INSERT INTO outbox_events
            (event_id, type, payload, status, attempts, next_attempt_at, created_at)
        VALUES (%s, %s, %s, 'PENDING', 0, %s, %s)
        """,
        (event["eventId"], event["type"], json.dumps(event["payload"]), now, now),
    )
    connection.execute("COMMIT")
except psycopg.IntegrityError:
    connection.execute("ROLLBACK")
    raise ValueError("Enrollment already exists")   # service đổi thành 409
```

Không gọi SMTP, không gọi mạng, không đọc file trong transaction. Nếu `INSERT enrollments` vi phạm
khoá chính (đã đăng ký) → rollback, trả `409 CONFLICT`, **không** sinh outbox event.

### 5.5. Luồng gửi (at-least-once)

```
mỗi lần drain (hoặc mỗi OUTBOX_POLL_INTERVAL giây):
  recover_expired_outbox(now)
      SENDING có locked_until <= now  ->  PENDING
  events = claim_outbox_batch(now, limit, lease_seconds)
  for event in events:
      try:
          transport(config, build_message(event))
          mark_outbox_sent(event_id, now)          -> SENT
      except Exception:
          mark_outbox_failed(...)                  -> PENDING (attempts+1) hoặc DEAD
```

- `claim_outbox_batch` chạy `SELECT` các event đến hạn, rồi `UPDATE` từng event với điều kiện
  `status = 'PENDING'` trong **cùng một transaction**; event được gán `locked_until = now + lease`.
- Hiện implementation phù hợp với **một worker trong một tiến trình**. Nếu chạy nhiều worker ở nhiều
  tiến trình, nên siết claim bằng `SELECT ... FOR UPDATE SKIP LOCKED` hoặc một câu
  `UPDATE ... RETURNING` để bảo đảm mỗi event chỉ được đúng một worker nhận.
- Retry dùng **delay cố định** `OUTBOX_RETRY_DELAY_SECONDS` (mặc định 2 giây), không exponential;
  đây là chủ đích để không trộn pattern #1 vào #8.
- Sau `OUTBOX_MAX_ATTEMPTS` (mặc định 5), event chuyển `DEAD` và giữ `last_error`.
- Vì at-least-once, email có thể trùng. Chống trùng ở phía người nhận bằng
  `Message-ID: <{event_id}@lms.local>` — đây là "hiệu ứng phụ được chấp nhận", không phải bug.
- `MAIL_TRANSPORT` cho phép bơm transport giả trong test, không gọi SMTP thật.

### 5.6. Nghiệm thu

- [x] Đăng ký thành công → có đúng 1 dòng `enrollments` **và** 1 dòng `outbox_events` PENDING
      trong cùng một lần commit.
- [x] Đăng ký trùng → 409, không sinh event mới, không gửi mail.
- [x] SMTP lỗi lần 1 → event quay lại PENDING với `attempts=1`, `next_attempt_at > now`;
      `drain_once` lần 2 (sau khi tua thời gian) → SENT, transport nhận đúng 1 email.
- [x] SMTP lỗi mãi → sau `OUTBOX_MAX_ATTEMPTS` event thành DEAD, `last_error` có nội dung, không
      mất bản ghi đăng ký.
- [x] Chạy `drain_once` 2 lần liên tiếp → chỉ 1 email (lần 2 không còn event PENDING).
- [x] Event SENDING quá lease được đưa về PENDING (khôi phục sau crash).
- [x] "Khôi phục sau sự cố": tạo event PENDING rồi tạo app mới trên cùng DB → `drain_once` gửi được.
- [x] Email có `Message-ID` ổn định theo `event_id`.
- [x] Sinh viên khác không đăng ký hộ được; instructor/admin gọi endpoint → 403.
- [x] CLI `flask outbox drain` / `status` hoạt động.
- [x] Form web tạo event; worker tắt trong test.
- [ ] **Chưa có** test nhiều worker/tiến trình tranh claim; xem ghi chú ở 5.5.

### 5.7. Cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `OUTBOX_MAX_ATTEMPTS` | 5 | Số lần thử trước khi DEAD |
| `OUTBOX_RETRY_DELAY_SECONDS` | 2 | Delay cố định giữa các lần thử |
| `OUTBOX_LEASE_SECONDS` | 60 | Thời gian giữ event ở SENDING |
| `OUTBOX_BATCH_SIZE` | 10 | Số event mỗi lần claim |
| `OUTBOX_POLL_INTERVAL` | 0 | 0 = tắt worker nền; > 0 = poll mỗi N giây |

## 6. Phối hợp 2 người (tránh đụng file)

| File | A (#3) | B (#8) |
|---|---|---|
| `app/store.py` | `init` (cột `version`), `update_grade`, `update_grade_if_version`, `read_grade_version` | `create_enrollment` + 5 hàm outbox |
| `app/grade_version_service.py` | toàn bộ file | — |
| `app/grades_v2.py` | toàn bộ file | — |
| `app/services.py` | `update_grade` (lõi) | `enroll_in_course` |
| `app/outbox.py` | — | toàn bộ file |
| `app/__init__.py` | không sửa | route `POST /me/enrollments` + CLI |
| `app/errors.py` | dùng `Conflict` sẵn có | dùng `Conflict` sẵn có |
| `tests/` | `test_grade_version.py` | `test_outbox.py` |

Thứ tự merge đề xuất: **A trước, B sau** (A sửa schema `enrollments`; B chỉ thêm bảng mới + hàm
mới). B rebase lên nhánh A, chạy lại `pytest -q` trước khi mở PR.

## 7. Checklist nghiệm thu chung

- [x] Đúng phạm vi: #3 chỉ thêm cột; #8 thêm 1 module + 1 bảng; không dùng thư viện làm sẵn pattern.
- [x] Logic chính nằm trong code của nhóm (SQL có điều kiện / claim + retry tự viết).
- [x] Không phá vỡ bất biến bảo mật: gate Bearer, CSRF cho form, RBAC ở route **và** service,
      audit không chứa mật khẩu/token.
- [x] Có test chứng minh hành vi trước/sau (stale version → 409; SMTP lỗi → PENDING/DEAD).
- [ ] Chưa có test song song 20 request cho #3.
- [ ] Chưa có test nhiều worker tranh claim cho #8.
- [x] README và ADR liên quan đã cập nhật.
- [ ] Chạy `powershell -File scripts/gate.ps1` ở trạng thái xanh trước khi nộp.

## 8. Kịch bản demo gợi ý (5 phút)

Chuẩn bị:

```powershell
$env:JWT_SECRET = "thay-bang-secret-cua-ban"  # gitleaks:allow
$env:DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:5432/lms"
flask --app app run
```

### #3 — hai tab sửa điểm

1. Mở 2 tab, cùng vào trang sửa điểm của giảng viên `an.gv@lms.test`.
2. Tab 1 lưu 9 → 200. Tab 2 (vẫn giữ version cũ) lưu 8 → 409 `CONFLICT`.
3. Kiểm tra DB và audit:

```powershell
psql $env:DATABASE_URL -c "SELECT student_id, score, version FROM enrollments WHERE course_id='c1';"
Get-Content audit.log -Tail 3
```

### #8 — SMTP lỗi rồi drain

1. Đặt `SMTP_HOST` sai, đăng ký khóa `c2` → 201, DB có enrollment, outbox PENDING.
2. Kiểm tra:

```powershell
flask --app app outbox status
psql $env:DATABASE_URL -c "SELECT event_id, status, attempts FROM outbox_events ORDER BY id DESC LIMIT 5;"
```

3. Sửa SMTP, chạy `flask --app app outbox drain` → SENT; kiểm tra lại `outbox status`.

## 9. Trạng thái triển khai

| Hạng mục | Trạng thái | Vị trí |
|---|---|---|
| Cột `enrollments.version` + `ALTER TABLE` cho DB cũ | Xong | `app/store.py::init` |
| Ghi điểm có điều kiện version | Xong | `app/store.py::update_grade_if_version` |
| Endpoint `GET/PUT .../v2` | Xong | `app/grades_v2.py` |
| Nghiệp vụ + audit cho v2 | Xong | `app/grade_version_service.py` |
| Test #3 | Xong (19 test) | `tests/test_grade_version.py` |
| ADR #3 | Xong | `docs/decisions/0013-optimistic-locking-diem.md` |
| Bảng `outbox_events` + các hàm claim/mark | Xong | `app/store.py` |
| Module outbox | Xong | `app/outbox.py` |
| Endpoint đăng ký + form web | Xong | `app/__init__.py`, `app/web.py` |
| Gửi mail có `Message-ID` | Xong | `app/emailer.py::send_email` |
| CLI | Xong | `flask outbox drain/status` |
| Test #8 | Xong (15 test) | `tests/test_outbox.py` |
| ADR #8 | Xong | `docs/decisions/0005-outbox-email-dang-ky.md` |

Đã chạy `pytest tests/test_grade_version.py tests/test_outbox.py -q` ngày 08/11/2026: **34 passed**.

**Khác biệt / giới hạn cần nói khi bảo vệ:**

- #3 dùng `expectedVersion` trong body và trả 409, không dùng `If-Match`/ETag/412/428 (theo ADR 0013).
- #3 hiện tách 2 file (`grade_version_service.py` và `grades_v2.py`). Nếu giảng viên đếm "module"
  theo số file, có thể gộp blueprint vào `app/__init__.py`; logic nghiệp vụ vẫn nằm ở
  `grade_version_service.py`.
- Endpoint lõi vẫn last-write-wins; chỉ endpoint v2 bảo vệ khỏi lost update.
- #8 dùng retry cố định, chưa có exponential backoff + jitter (đó là pattern #1).
- #8 hiện phù hợp một worker; nếu chạy nhiều worker cần siết claim (xem 5.5).
- Outbox còn được dùng cho `announcement.posted` (thông báo lớp), không chỉ email đăng ký.

## 10. Tham chiếu

- [README](../README.md) — cách chạy, biến môi trường, trạng thái dự án.
- [ADR 0005](decisions/0005-outbox-email-dang-ky.md) — transactional outbox.
- [ADR 0013](decisions/0013-optimistic-locking-diem.md) — optimistic locking cho điểm.
- `app/store.py`, `app/outbox.py`, `app/grade_version_service.py`, `app/grades_v2.py`.
- `tests/test_grade_version.py`, `tests/test_outbox.py`.
