# 0012 — Thông báo, thảo luận: quyền, văn bản thuần và quyền xoá

- **Trạng thái:** Đã chấp nhận
- **Ngày:** 2026-11-06
- **Người quyết định:** nhóm phát triển MiniLMS
- **Liên quan:** `app/forum.py`, `app/forum_service.py`, `app/store.py`

## Bối cảnh

Bước 3.5 cần Announcement, Thread, Comment nhưng đề không kèm ma trận quyền cho ba tài nguyên
này. Đề có nêu "xoá comment: tác giả, instructor của môn, hoặc admin" và "nội dung là văn bản
thuần, trả nguyên văn dưới dạng JSON (không render HTML ở server)".

## Quyết định

- Ba bảng: `announcements`, `threads`, `comments`, id `an_/th_/cm_<uuid4>`.
- Quyền xem (và là thành viên lớp): ADMIN, giảng viên của môn, sinh viên đã ghi danh.
- Tạo **announcement**: ADMIN + giảng viên của môn. Sinh viên chỉ đọc.
- Tạo **thread/comment**: mọi thành viên lớp (ADMIN, GV của môn, SV đã ghi danh).
- Xoá announcement/thread/comment: **chỉ ADMIN + giảng viên của môn**. Tác giả là sinh viên
  **không** được tự xoá (khác câu chữ của đề — theo chốt trực tiếp của chủ dự án).
- Nội dung lưu và trả nguyên văn; không có endpoint render HTML, không escape thay client.
- Giới hạn: title ≤ 200, body thread/announcement ≤ 5000, comment ≤ 2000.
- Audit: `ANNOUNCEMENT_CREATE/DELETE`, `THREAD_CREATE/DELETE`, `COMMENT_CREATE/DELETE`.

## Hệ quả

### Tích cực

- Một quy tắc "thành viên lớp" dùng chung cho xem/tạo thread/comment, dễ hiểu và dễ test.
- Xoá nội dung do một người quản lý môn quyết định, tránh tranh chấp giữa sinh viên.
- Xoá thread tự xoá comment của thread trong cùng transaction.

### Đánh đổi / rủi ro

- **Lệch đề**: đề cho tác giả xoá comment của mình; nhóm chốt không cho. Nếu giảng viên chấm
  theo câu chữ, cần đổi `update_comment_delete_policy` (một chỗ trong `forum_service`) và bổ sung test.
- Sinh viên không xoá được nội dung của mình → cần GV can thiệp.
- Chưa có phân trang; lớp đông sẽ trả toàn bộ thread/comment.

### Việc phải làm kèm theo

- Nếu đổi quyền xoá, tạo ADR mới và sửa cả test `test_only_course_staff_deletes_comment`.
- Không thêm render HTML/Markdown ở server.

## Phương án đã cân nhắc

| Phương án | Vì sao không chọn |
|---|---|
| Tác giả + GV + ADMIN được xoá (như đề) | Chủ dự án chọn chỉ GV + ADMIN |
| Mọi thành viên lớp xoá tự do | Không kiểm soát được nội dung |
| Lưu HTML đã render | Trái yêu cầu văn bản thuần, tăng rủi ro XSS |
