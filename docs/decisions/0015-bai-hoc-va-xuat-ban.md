# 0015 — Bài học và xuất bản khoá học

- **Trạng thái:** Đã chấp nhận (2026-11-09)
- **Bối cảnh:** Ma trận phân quyền yêu cầu giảng viên soạn bài học, xuất bản/ẩn khoá,
  quản lý học viên trong khoá; sinh viên học bài và theo dõi tiến độ. Trước đây khoá học chỉ
  có tài liệu/bài tập/quiz, chưa có khái niệm bài học hay trạng thái xuất bản.
- **Quyết định:**
  1. Thêm bảng `lessons` (thuộc `courses`, có `position`, `is_preview`) và bảng
     `lesson_progress` (khoá chính `user_id + lesson_id`).
  2. Thêm cột `courses.published` (mặc định 1 cho dữ liệu cũ; khoá mới tạo mặc định xuất bản,
     giảng viên có thể ẩn).
  3. Quy tắc hiển thị danh sách: ADMIN thấy tất cả; giảng viên thấy khoá đã xuất bản + khoá của
     mình; sinh viên thấy khoá đã ghi danh + khoá đã xuất bản. Chi tiết khoá vẫn yêu cầu là
     thành viên (ADMIN/GV phụ trách/SV đã ghi danh).
  4. Quyền quản lý bài học dùng chung `authorize_manage` của khoá học (ADMIN hoặc GV phụ trách);
     sinh viên đã ghi danh được xem và đánh dấu hoàn thành.
  5. Mọi thao tác có endpoint `/ui/...` và nút bấm tương ứng; API JSON nằm trong blueprint
     `lessons` (và các route publish/admin bổ sung).
- **Hệ quả:** Thêm 2 bảng, 1 cột; `GET /courses` trả thêm trường `published`; test cũ về phạm vi
  danh sách khoá học được cập nhật theo quy tắc mới. Xoá khoá học dọn kèm bài học và tiến độ.
