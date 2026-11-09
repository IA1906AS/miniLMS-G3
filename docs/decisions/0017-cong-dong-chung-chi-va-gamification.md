# 0017 — Cộng đồng, chứng chỉ và gamification

- **Trạng thái:** Đã chấp nhận (2026-11-09)
- **Bối cảnh:** Ma trận quyền còn thiếu nhắn tin trực tiếp, live session, bình luận dưới bài học,
  chứng chỉ hoàn thành khoá, bảng xếp hạng, huy hiệu và chuỗi ngày học liên tiếp.
- **Quyết định:**
  1. Bảng mới: `messages`, `live_sessions`, `lesson_comments`, `certificates`, `badges`,
     `user_badges`, `activity_days`; thêm `courses.cert_min_grade` và
     `courses.cert_require_lessons`.
  2. Tin nhắn chỉ cho phép giữa hai người dùng có chung khoá học (hoặc ADMIN). Live session do
     ADMIN/GV phụ trách tạo; thành viên khoá học xem và bấm "Tham gia".
  3. Chứng chỉ: điều kiện cấu hình theo khoá (hoàn thành tất cả bài học + điểm TB tối thiểu).
     Sinh viên được tự cấp khi đủ điều kiện (`GET /me/certificates`), GV/ADMIN cấp hoặc thu hồi
     thủ công. Chứng chỉ có mã `CERT-...` và trang HTML in được.
  4. Xếp hạng: điểm thành tích = bài học*5 + điểm TB*10 + điểm quiz TB*10 + điểm quiz cao nhất*5.
  5. Huy hiệu: ADMIN tạo và trao tay; hệ thống tự trao "Bài học đầu tiên", "Siêng năng",
     "Cao thủ quiz". Streak tính từ bảng `activity_days` (ghi khi hoàn thành bài/quiz).
- **Hệ quả:** Thêm 7 bảng và 2 cột; xoá người dùng/khoá học dọn kèm dữ liệu liên quan.
