# 0011 — Bài tập, nộp bài và chống nộp trùng

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/assignments.py`, `app/assignment_service.py`, `app/store.py`

## Bối cảnh

Bước 3.4 yêu cầu Assignment/Submission, chặn nộp sau hạn ở server, và chống tạo bài nộp
trùng. Đề để ngỏ mã lỗi khi nộp trễ (403 hoặc 409) và thời điểm được kiểm tra bằng đồng hồ
inject được. Submission cần id không đoán được và mỗi cặp (assignment, student) chỉ một bài.

## Quyết định

- Hai bảng mới: `assignments(id, course_id, title, description, due_at, created_by, created_at)`
  và `submissions(id, assignment_id, student_id, content, submitted_at)` với
  `UNIQUE (assignment_id, student_id)`.
- Id dạng `a_<uuid4>` và `s_<uuid4>`.
- `dueAt` lưu **epoch giây**; API chấp nhận số (epoch) hoặc chuỗi ISO-8601 (có/không `Z`).
- Hạn nộp kiểm tra bằng `state["now"]()` (đồng hồ inject được), không dùng `time.time()` trực tiếp.
- Nộp trễ → **403 FORBIDDEN** (theo chốt của nhóm).
- Quyền tạo bài tập: **ADMIN** hoặc **giảng viên của môn**; sinh viên/GV môn khác → 403.
- Gửi lại bài:
  - cùng nội dung → **200** kèm bài cũ, không tạo bản ghi, không audit;
  - khác nội dung → **409 CONFLICT**.
- Sinh viên chỉ thấy bài nộp của mình; GV của môn và admin thấy cả lớp; sinh viên ngoài môn → 403.

## Hệ quả

### Tích cực

- Client retry an toàn (idempotent theo nội dung), không sinh bản ghi trùng.
- Hạn nộp kiểm tra ở server, không tin đồng hồ client; test được bằng `CLOCK`.
- UNIQUE ở DB là chốt cuối, kể cả khi service bị gọi song song.

### Đánh đổi / rủi ro

- So sánh nội dung là so chuỗi chính xác: thêm một dấu cách bị coi là bài khác → 409.
- Không có endpoint sửa bài nộp; muốn đổi phải có quy định mới (và ADR mới).
- `dueAt` trả về dạng epoch trong JSON, client phải tự format.

### Việc phải làm kèm theo

- Đổi cách so hạn (ví dụ theo múi giờ) phải sửa `authorize_submit`, không sửa rải rác.
- Không trả `content` của sinh viên khác cho sinh viên.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| 409 khi nộp trễ | Đề cho phép, nhưng 409 đã dành cho trùng nội dung |
| Lưu dueAt dạng chuỗi ISO | So sánh thời gian phức tạp, dễ sai múi giờ |
| Cho phép nhiều bài nộp, lấy bài mới nhất | Phá yêu cầu idempotency "một bài mỗi cặp" |
| Chặn nộp trễ ở client | Không đáng tin, đề yêu cầu kiểm tra ở server |
