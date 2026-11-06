# Đề xuất 2 defensive pattern cho MiniLMS

Tài liệu này chọn 2 pattern trong danh sách 10 pattern của bài tập, gắn trực tiếp với mã nguồn
hiện có trong repo, và mô tả cách cài đặt + cách nghiệm thu.

## 1. Kết luận nhanh

| Thành viên | Pattern | Tính năng LMS | Module mới | Bảng mới |
|---|---|---|---|---|
| A | **#3 Optimistic locking** | Sửa điểm | `app/optimistic.py` | không cần (thêm cột `version` vào `enrollments`) |
| B | **#8 Transactional outbox** | Email xác nhận đăng ký khóa học | `app/outbox.py` | `outbox_events` |

Lý do chọn cặp này:

- Cả hai đều nằm trên miền dữ liệu **đã có** trong repo (`enrollments`, `emailer`), nên không phải
  dựng thêm một tính năng lớn chỉ để có chỗ gắn pattern.
- Hai rủi ro khác nhau về bản chất: #3 là **tính đúng đắn khi ghi đồng thời** (lost update),
  #8 là **tính bền của sự kiện khi có hai lần ghi** (dual-write). Không trùng lặp ý tưởng,
  thuyết trình được hai góc nhìn bổ sung cho nhau.
- Cả hai đều **test được bằng pytest** trên hạ tầng có sẵn (82 test đang pass), và **demo được
  trong 5 phút** bằng 2 tab trình duyệt / 1 lần tắt SMTP.
- Mỗi pattern chỉ cần **1 module + tối đa 1 bảng**, đúng quy định phạm vi.

## 2. Hiện trạng repo (căn cứ để chọn)

Ứng dụng Flask + SQLite, không ORM, không queue, không worker:

| Thành phần | Vị trí | Ghi chú liên quan |
|---|---|---|
| Bảng dữ liệu | `app/store.py` | `users`, `courses`, `enrollments(course_id, student_id, score)`, `password_reset_tokens`, `oauth_accounts` |
| Sửa điểm | `app/services.py::update_grade` → `store.update_grade` | Ghi đè vô điều kiện `UPDATE enrollments SET score = ?` — **last-write-wins** |
| Đọc điểm | `GET /courses/<id>/grades` | Trả `studentId`, `score`; không có version/ETag |
| Gửi mail | `app/emailer.py` | Chỉ dùng cho reset mật khẩu; ném `RuntimeError` nếu thiếu SMTP |
| Nạp lại cache | `app/gate.py::_gate` gọi `store.refresh(state)` **mỗi request** | Cache in-memory luôn được đồng bộ từ DB trước khi vào handler |
| Lỗi | `app/errors.py` | Đã có `Conflict` (409), `ValidationError` (400); **chưa có** 412/428 |
| Kiểm thử | `tests/` | `82 passed`; có sẵn fixture `app`, `client`, helper `login`, `auth` |

Hệ quả quan trọng: vì `store.refresh` chạy mỗi request, mọi cột mới thêm vào bảng phải được
bổ sung vào câu `SELECT` trong `refresh()` — nếu không, cache sẽ thiếu dữ liệu dù DB đúng.

## 3. Vì sao không chọn các pattern còn lại

| # | Pattern | Đánh giá cho repo này |
|---|---|---|
| 1 | Exponential backoff + jitter (email điểm) | Làm được, nhưng **trùng ý tưởng với #8** (độ tin cậy của email) → 2 người sẽ va nhau về khái niệm, và cần thêm bảng trạng thái gửi |
| 2 | Idempotency key (nộp bài tập) | Phải dựng mới tính năng "bài tập/bài nộp", và thường tốn **2 bảng** (bài nộp + khoá idempotency) → sát/vượt giới hạn phạm vi |
| 4 | Token bucket (trợ lý AI) | Repo không có AI assistant → phải giả lập dịch vụ ngoài, dễ bị hỏi "pattern có thật sự cần không" |
| 5 | Circuit breaker (đạo văn) | Cần một dịch vụ ngoài không tồn tại; nếu tự viết stub thì bài trở thành "tự chế lỗi để chống lỗi" |
| 6 | Timeout + fallback (dashboard) | Không có dashboard và không có dịch vụ chậm nào; chi phí dựng mới > giá trị chứng minh |
| 7 | Máy trạng thái (lượt làm bài) | Phải dựng toàn bộ tính năng thi + ngân hàng câu hỏi: vượt xa "một tính năng nhỏ" |
| 9 | Bulkhead (xuất báo cáo điểm) | **Phương án dự phòng tốt nhất** nếu #8 quá nặng: chỉ cần thread pool + semaphore, không cần bảng |
| 10 | Giữ chỗ có thời hạn (lớp giới hạn sĩ số) | Khả thi nhưng cần thêm `capacity` + bảng giữ chỗ + sweeper hết hạn; tranh chấp ghi trên SQLite khó demo gọn |

## 4. Pattern A — #3 Optimistic locking cho "Sửa điểm"

### 4.1 Rủi ro cần chứng minh

Hai giảng viên (hoặc 2 tab của cùng một người) cùng mở bảng điểm:

```
T1: A đọc điểm u4 = 7.5 (version 2)
T2: B đọc điểm u4 = 7.5 (version 2)
T3: A lưu 8.0   -> DB = 8.0
T4: B lưu 9.0   -> DB = 9.0   (mất thay đổi của A, không ai biết)
```

Hiện tại `update_grade` không có khái niệm "phiên bản", nên T4 luôn thắng. Đây chính là
"người lưu sau ghi đè thay đổi của người trước".

### 4.2 Phạm vi

- Module mới: `app/optimistic.py` — chứa `parse_if_match`, `version_of`, `apply_grade_update`
  (hàm thuần, không phụ thuộc Flask) để test được ở tầng service.
- Dữ liệu: thêm cột, không thêm bảng:

```sql
ALTER TABLE enrollments ADD COLUMN version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE enrollments ADD COLUMN updated_at REAL;
```

> Nếu giảng viên yêu cầu "đúng một bảng mới" cho mỗi pattern, dùng bảng
> `grade_versions(course_id, student_id, version, updated_at, updated_by)` làm nguồn sự thật
> của version và giữ nguyên `enrollments`. Cách này tốn thêm 1 lần join nhưng vẫn trong phạm vi.

### 4.3 Hợp đồng HTTP

Đọc một điểm (thêm mới, phục vụ If-Match):

```
GET /courses/c1/grades/u4
200 OK
ETag: "2"
{"studentId": "u4", "score": 7.5, "version": 2}
```

Ghi điểm:

```
PUT /courses/c1/grades/u4
If-Match: "2"
{"score": 9}
```

| Tình huống | Mã | Body |
|---|---|---|
| Thiếu `If-Match` | `428` | `{"error": "PRECONDITION_REQUIRED"}` |
| `If-Match` sai định dạng | `400` | `{"error": "VALIDATION_ERROR"}` |
| Version cũ | `412` | `{"error": "STALE_VERSION", "current": {"score": 8.0, "version": 3}}` |
| Hợp lệ | `200` | `{"courseId": "c1", "studentId": "u4", "score": 9, "version": 3}` + `ETag: "3"` |
| Không có bản ghi | `404` | `{"error": "NOT_FOUND"}` |

Cần thêm 2 lớp lỗi trong `app/errors.py`: `PreconditionRequired` (428) và `StaleVersion` (412).
`StaleVersion` nên mang theo `current` để UI hiện hộp thoại "dữ liệu đã đổi, tải lại?".

### 4.4 Cài đặt cốt lõi

Điểm mấu chốt là **một câu UPDATE có điều kiện**, không phải đọc-rồi-ghi:

```python
cursor = connection.execute(
    """
    UPDATE enrollments
       SET score = ?, version = version + 1, updated_at = ?
     WHERE course_id = ? AND student_id = ? AND version = ?
    """,
    (score, now, course_id, student_id, expected_version),
)
if cursor.rowcount != 1:
    # phân biệt "không tồn tại" và "version cũ" trong cùng transaction
    row = connection.execute(
        "SELECT score, version FROM enrollments WHERE course_id = ? AND student_id = ?",
        (course_id, student_id),
    ).fetchone()
    if row is None:
        raise NotFound()
    raise StaleVersion(current={"score": row[0], "version": row[1]})
```

Bọc trong `BEGIN IMMEDIATE ... COMMIT` như các hàm hiện có trong `store.py`, và giữ nguyên
`state["lock"]` để không phá vỡ mô hình đang chạy.

Các điểm phải sửa cho khớp codebase:

1. `store.init`: thêm 2 cột vào `CREATE TABLE enrollments` (DB mới) và một bước
   `ALTER TABLE` có kiểm tra `PRAGMA table_info` (DB cũ `lms.sqlite3` đã tồn tại).
2. `store.refresh`: đọc thêm `version, updated_at`; đổi cache thành
   `state["enrollments"][(c, s)] = {"score": ..., "version": ...}` — **hoặc** giữ nguyên dict
   score và thêm `state["enrollment_versions"]` để giảm diện sửa. Cách thứ hai ít phá vỡ
   `services.get_grades` và `web.account` hơn.
3. `store.update_grade(..., expected_version)`: trả về version mới, ném `StaleVersion`/`NotFound`.
4. `services.update_grade`: nhận `expected_version`, audit thêm `oldVersion`/`newVersion`,
   trả kèm `version`.
5. `app/__init__.py`: route `PUT` đọc `If-Match` qua `optimistic.parse_if_match`; thêm route `GET`
   một điểm để lấy ETag. Route mới vẫn phải qua `@require_role` và vẫn phải chịu `gate`
   (gate đã ép Bearer cho mọi route không thuộc `web.`) — không cần sửa `gate.py`.
6. `web.py` (nếu có form sửa điểm): nhúng `version` vào hidden input và gửi lại khi submit.
   Nếu chưa có form, bỏ qua — nhưng nên có để demo trực quan.

### 4.5 Nghiệm thu

- [ ] `PUT` không có `If-Match` → 428, điểm không đổi.
- [ ] Hai client cùng đọc version 2; client 1 ghi thành công lên version 3; client 2 ghi với
      `If-Match: "2"` → 412, body có `current.score` = giá trị mới nhất, DB vẫn là 9/8 của client 1.
- [ ] Client 2 đọc lại, ghi với `"3"` → 200, version = 4.
- [ ] 20 request song song cùng `If-Match: "2"` → **đúng 1** nhận 200, 19 nhận 412
      (test bằng `ThreadPoolExecutor` + `app.test_client()` riêng cho mỗi thread).
- [ ] Sinh viên/giảng viên khác khóa vẫn 403; sinh viên chưa ghi danh vẫn 404.
- [ ] Audit log có `oldVersion`/`newVersion`, không có mật khẩu/token (test A19 vẫn xanh).
- [ ] Toàn bộ test cũ vẫn pass; test A14 (`update` trả `{courseId, studentId, score}`) được cập
      nhật để chấp nhận thêm trường `version`.

## 5. Pattern B — #8 Transactional outbox cho "Email xác nhận đăng ký khóa học"

### 5.1 Rủi ro cần chứng minh

Đăng ký khóa học cần 2 việc: ghi `enrollments` và gửi email xác nhận. Nếu viết thẳng:

```python
store.enroll(...)              # đã commit
emailer.send_confirmation(...) # SMTP chết -> sinh viên đã vào lớp nhưng không có mail
```

hoặc gửi mail trước rồi commit thất bại → email "ma" cho một đăng ký không tồn tại.
Đây là **dual-write**: hai hệ thống (SQLite, SMTP) không nằm trong một transaction.

### 5.2 Phạm vi

- Tính năng: `POST /me/enrollments` (body `{"courseId": ...}`) — sinh viên tự đăng ký (hiện chỉ có dữ liệu
  seed, chưa có endpoint).
- Module mới: `app/outbox.py` — `enqueue`, `claim_batch`, `mark_sent`, `mark_failed`,
  `drain_once`.
- Bảng mới (đúng 1 bảng):

```sql
CREATE TABLE outbox_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL UNIQUE,       -- cũng dùng làm Message-ID
    type         TEXT NOT NULL,              -- 'enrollment.confirmed'
    payload      TEXT NOT NULL,              -- JSON: course, student, email
    status       TEXT NOT NULL DEFAULT 'PENDING',  -- PENDING|SENDING|SENT|DEAD
    attempts     INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL,
    created_at   REAL NOT NULL,
    sent_at      REAL,
    last_error   TEXT
);
CREATE INDEX idx_outbox_due ON outbox_events (status, next_attempt_at);
```

`event_id` sinh bằng `secrets.token_urlsafe(16)` **trong transaction**; UNIQUE đảm bảo không
tạo trùng nếu logic bị gọi lặp.

### 5.3 Luồng ghi (transaction duy nhất, không I/O)

```python
with state["lock"]:
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("INSERT INTO enrollments (course_id, student_id, score, version) ...")
    connection.execute(
        "INSERT INTO outbox_events (event_id, type, payload, next_attempt_at, created_at) ...")
    connection.execute("COMMIT")
```

Không gọi SMTP, không gọi mạng, không đọc file trong transaction. Nếu `INSERT enrollments` vi phạm
PK (đã đăng ký) → rollback, trả `409 CONFLICT`, **không** sinh outbox event.

### 5.4 Luồng gửi (at-least-once)

```
loop mỗi 2s (hoặc `flask outbox drain`, hoặc gọi trong test):
  claim  = UPDATE outbox_events SET status='SENDING'
           WHERE id IN (SELECT id FROM outbox_events
                        WHERE status='PENDING' AND next_attempt_at <= :now
                        ORDER BY id LIMIT 10)
  for row in claimed:
      try:
          transport(payload)          # hàm bơm vào, mặc định là emailer
          UPDATE ... SET status='SENT', sent_at=:now
      except Exception as e:
          attempts += 1
          if attempts >= MAX_ATTEMPTS: status='DEAD'
          else: status='PENDING'; next_attempt_at = now + min(CAP, BASE * 2**attempts) + jitter
```

- `claim` phải là **một câu UPDATE** (không SELECT-rồi-UPDATE) để hai worker không giành cùng event.
- Nếu tiến trình chết giữa `SENDING` và `SENT`: thêm `locked_until` và coi event `SENDING` quá hạn
  là cần gửi lại (at-least-once), hoặc đơn giản là cho phép chạy lại toàn bộ `SENDING` sau restart.
- Vì at-least-once, email có thể trùng. Chống trùng ở phía người nhận bằng cách đặt
  `Message-ID: <{event_id}@lms.local>` — nêu rõ trong báo cáo đây là "hiệu ứng phụ được chấp nhận",
  không phải bug.
- `emailer.py` hiện tự dựng `smtplib` và ném `RuntimeError` khi thiếu cấu hình. Nên tách
  `transport` qua `app.config["MAIL_TRANSPORT"]` (mặc định = hàm SMTP thật) để test bơm fake
  và để `drain_once` test được mà không cần mạng.

### 5.5 Nghiệm thu

- [ ] Đăng ký thành công → có đúng 1 dòng `enrollments` **và** 1 dòng `outbox_events` PENDING
      trong cùng một lần commit (test: transport giả ném lỗi, kiểm tra cả hai bảng vẫn có dữ liệu).
- [ ] SMTP lỗi lần 1 → event quay lại PENDING với `attempts=1`, `next_attempt_at > now`;
      `drain_once` lần 2 (sau khi tua thời gian) → SENT, transport nhận đúng 1 email.
- [ ] SMTP lỗi mãi → sau `MAX_ATTEMPTS` event thành DEAD, `last_error` có nội dung, không mất
      bản ghi đăng ký.
- [ ] Chạy `drain_once` 2 lần liên tiếp → chỉ 1 email (lần 2 không còn event PENDING).
- [ ] Đăng ký trùng (cùng course + student) → 409, không sinh event mới, không gửi mail.
- [ ] "Khôi phục sau sự cố": tạo event PENDING rồi tạo app mới trên cùng file DB → `drain_once`
      gửi được (chứng minh sự kiện nằm trong DB, không nằm trong RAM).
- [ ] Sinh viên khác không đăng ký hộ được; instructor/admin gọi endpoint → 403.

## 6. Phối hợp 2 người (tránh đụng file)

| File | A (#3) | B (#8) |
|---|---|---|
| `app/store.py` | `init` (cột version), `refresh`, `update_grade` | thêm `enroll_student` + 3 hàm outbox |
| `app/services.py` | sửa `update_grade`, thêm `get_grade` | thêm `enroll_in_course` |
| `app/__init__.py` | route GET 1 điểm + sửa PUT | route POST enrollments + CLI `outbox drain` |
| `app/errors.py` | thêm 412/428 | dùng `Conflict` sẵn có |
| `app/outbox.py`, `app/optimistic.py` | — | — |

Thứ tự merge đề xuất: **A trước, B sau** (A sửa schema `enrollments` và `refresh`, B chỉ thêm
bảng mới + hàm mới). B rebase lên nhánh A, chạy lại `pytest -q` trước khi mở PR; cả hai cùng
chỉnh `tests/` ở file riêng (`test_optimistic_lock.py`, `test_outbox.py`).

## 7. Checklist nghiệm thu chung (dùng cho cả 2 pattern)

- [ ] Đúng phạm vi: 1 tính năng, ≤ 1 module mới, ≤ 1 bảng mới, không dùng thư viện làm sẵn pattern.
- [ ] Logic chính nằm trong code của nhóm (SQL có điều kiện / claim batch tự viết).
- [ ] Không phá vỡ các bất biến bảo mật đang có: gate Bearer, CSRF cho form, RBAC ở route **và**
      service, audit log không chứa bí mật.
- [ ] Có test chứng minh **trước khi sửa thì lỗi, sau khi sửa thì hết** (demo bằng cách tạm bỏ
      điều kiện version / tạm gửi mail trực tiếp).
- [ ] Có kịch bản demo 3–5 phút, chạy được trên máy sạch (`pytest -q` + 2 tab trình duyệt).
- [ ] README có mục mô tả pattern, biến môi trường mới (`OUTBOX_POLL_INTERVAL`, `OUTBOX_MAX_ATTEMPTS`).

## 8. Kịch bản demo gợi ý (5 phút)

1. **#3**: mở 2 tab, cùng vào `/account` (hoặc trang sửa điểm) của giảng viên `an.gv@lms.test`.
   Tab 1 lưu 9 → OK. Tab 2 (vẫn đang giữ version cũ) lưu 8 → hộp thoại "Điểm đã được người khác
   cập nhật (hiện tại 9)" và nút tải lại. Mở `audit.log` cho thấy 2 dòng `oldVersion/newVersion`.
2. **#8**: đặt `SMTP_HOST` sai, đăng ký khóa `c2` → 201, DB có enrollment, outbox PENDING,
   UI báo "xác nhận sẽ được gửi". Sửa SMTP, chạy `flask outbox drain` → SENT, hộp thư có mail.
   `sqlite3 lms.sqlite3 "select status, attempts from outbox_events"`.

## 9. Trạng thái triển khai

Pattern **#8 đã được cài đặt** trong repo (pattern #3 chưa):

| Hạng mục | Vị trí |
|---|---|
| Bảng `outbox_events` + các hàm claim/mark | `app/store.py` (`create_enrollment`, `claim_outbox_batch`, `mark_outbox_sent`, `mark_outbox_failed`, `recover_expired_outbox`, `outbox_counts`) |
| Module outbox (build message, drain, worker) | `app/outbox.py` |
| Endpoint đăng ký | `POST /me/enrollments` trong `app/__init__.py`, service `services.enroll_in_course` |
| Nút đăng ký trên giao diện | `app/web.py::enroll_course`, `app/templates/account.html` |
| Gửi mail có `Message-ID` | `app/emailer.py::send_email` |
| CLI | `flask outbox drain [--limit N]`, `flask outbox status` |
| Test nghiệm thu | `tests/test_outbox.py` (12 test) |


