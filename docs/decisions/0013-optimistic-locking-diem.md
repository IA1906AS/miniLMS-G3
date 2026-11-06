# 0013 — Optimistic locking cho điểm qua endpoint `/v2`

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/grades_v2.py`, `app/grade_version_service.py`, `app/store.py`

## Bối cảnh

Bước 3.6 (tuỳ chọn) yêu cầu chống ghi đè điểm nhưng **không được đổi hợp đồng** của
`PUT /courses/<id>/grades/<sid>` (đang last-write-wins, trả `{courseId, studentId, score}`)
và của `GET .../grades` (trả `[{studentId, score}]`, test A7/A14 phụ thuộc chính xác).

## Quyết định

- Thêm cột `enrollments.version INTEGER NOT NULL DEFAULT 0` (có `ALTER TABLE` cho DB cũ).
- **Cả** endpoint lõi và endpoint v2 đều tăng `version` khi ghi điểm; response của endpoint lõi
  giữ nguyên từng field.
- Endpoint mới:
  - `GET /courses/<id>/grades/<sid>/v2` → `{courseId, studentId, score, version}`
  - `PUT .../v2` body `{score, expectedVersion}` → 200 `{..., version}`; version lệch → **409 CONFLICT**
- So khớp version bằng **một câu UPDATE có điều kiện** (`... AND version = ?`) trong
  `BEGIN IMMEDIATE`; `rowcount = 0` → phân biệt 404 (mất bản ghi) và 409.
- Thứ tự lỗi của v2: 401 → 404 (môn) → 403 → 400 (body) → 404 (ghi danh) → 409.
- Audit ghi `UPDATE_GRADE` kèm `oldScore`, `newScore`, `version`.

## Hệ quả

### Tích cực

- Endpoint lõi không đổi: test A1–A19 vẫn xanh, client cũ không cần sửa.
- Client v2 phát hiện được cả thay đổi do client cũ ghi (vì core cũng tăng version).
- So khớp version nằm trong DB nên an toàn cả khi hai request chạy song song.

### Đánh đổi / rủi ro

- Client v2 phải gọi `GET .../v2` trước khi ghi; nếu dùng `GET` lõi thì không có version.
- Hai endpoint cùng ghi điểm là hai đường vào; quy tắc nghiệp vụ phải sửa ở cả hai nếu đổi.
- 409 không kèm version hiện tại (theo quy ước `{"error": CODE}`); client phải GET lại.

### Việc phải làm kèm theo

- Không đổi response của endpoint lõi; nếu cần thêm version cho client cũ thì tạo ADR mới.
- Mọi ghi điểm mới phải đi qua `store.update_grade`/`store.update_grade_if_version`.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| `If-Match`/ETag chuẩn HTTP | Đề yêu cầu body `{score, expectedVersion}` |
| Không tăng version ở endpoint lõi | Client v2 không phát hiện được ghi đè từ client cũ |
| Bảng `grade_versions` riêng | Thêm join, không cần thiết cho một cột đếm |
| Trả version trong `GET .../grades` | Phá hợp đồng A7/A14 |
