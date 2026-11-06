# 0009 — Giảng viên mở môn qua yêu cầu cần admin duyệt

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS (theo yêu cầu sản phẩm)
- **Liên quan:** `app/courses.py`, `app/course_service.py`, `app/store.py`

## Bối cảnh

Giai đoạn 3 yêu cầu `POST /courses` nhưng không nói ai được tạo. Giảng viên có quyền thấp
hơn admin; nếu cho giảng viên tạo môn trực tiếp thì họ tự gán mình dạy bất kỳ môn nào, phá
mô hình phân quyền hai cấp. Đồng thời quy định mới yêu cầu id tài nguyên không đoán được
(uuid4), trong khi seed đang dùng `c1`, `c2`.

## Quyết định

- **Chỉ ADMIN tạo môn trực tiếp**: `POST /courses` với `{name, instructorId}`; `instructorId`
  phải tồn tại (404) và có role `INSTRUCTOR` (400). Môn mới nhận id `c_<uuid4>`.
- **Giảng viên gửi yêu cầu**: `POST /course-requests {name}` → bản ghi `PENDING` trong bảng
  `course_requests`, gắn với `instructor_id` của người gửi.
- **Admin duyệt/từ chối**: `POST /course-requests/<id>/approve|reject`. Duyệt tạo môn và đóng
  yêu cầu **trong cùng một transaction** (`store.approve_course_request`); duyệt lại → 409.
- Giảng viên chỉ thấy yêu cầu của mình; admin thấy tất cả; sinh viên 403.
- Seed giữ `c1`, `c2` để không phá test A1–A19; chỉ tài nguyên tạo qua API mới dùng uuid4.

## Hệ quả

### Tích cực

- Phân quyền hai cấp rõ ràng; giảng viên không tự mở môn.
- Duyệt môn là thao tác nguyên tử: không có môn "mồ côi" khi yêu cầu đã APPROVED.
- Audit đủ `COURSE_CREATE`, `COURSE_REQUEST`, `COURSE_APPROVE`, `COURSE_REJECT`.

### Đánh đổi / rủi ro

- Thêm một bảng và một vòng đời trạng thái (`PENDING → APPROVED | REJECTED`) phải giữ nhất quán.
- Admin vẫn phải duyệt thủ công; chưa có thông báo cho giảng viên khi bị từ chối.
- Không cho sửa/xoá yêu cầu sau khi gửi; muốn đổi thì gửi yêu cầu mới.

### Việc phải làm kèm theo

- Mọi thay đổi trạng thái yêu cầu phải qua `store` (không UPDATE rải rác).
- Không cho client tự đặt `status` hay `instructorId` khi gửi yêu cầu.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Giảng viên tạo môn trực tiếp | Tự gán quyền dạy, phá phân cấp |
| Admin tạo hộ, không có yêu cầu | Không có luồng đề xuất; admin phải biết trước |
| Yêu cầu lưu ở bộ nhớ | Mất khi restart, không audit được |
