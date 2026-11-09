# 0016 — Báo cáo tiến độ và quiz nâng cao

- **Trạng thái:** Đã chấp nhận (2026-11-09)
- **Bối cảnh:** Ma trận quyền yêu cầu giảng viên xem báo cáo khoá học, thống kê pass/fail,
  bảng điểm lớp, export CSV; sinh viên xem tiến độ bản thân; quiz cần sửa được và có tuỳ chọn
  cho sinh viên xem đáp án sau khi nộp.
- **Quyết định:**
  1. Thêm cột `quizzes.allow_answers` (mặc định 0). `PATCH /quizzes/<id>` cập nhật quiz và
     thay danh sách câu hỏi trong một transaction.
  2. `GET /quiz-attempts/<id>/answers` trả đáp án đúng cho chủ lượt làm nếu quiz cho phép,
     hoặc cho ADMIN/GV phụ trách; lượt chưa nộp bị từ chối.
  3. `store.course_report` tổng hợp theo sinh viên: bài học hoàn thành, bài tập đã nộp/đã chấm,
     điểm trung bình, lượt quiz, điểm quiz trung bình, pass/fail (điểm TB >= 5).
  4. Endpoint báo cáo: `GET /courses/<id>/report` (ADMIN/GV), `GET /me/progress` (SV),
     `GET /admin/report` (ADMIN). Web có trang báo cáo, bảng xếp hạng điểm và export CSV.
- **Hệ quả:** Không đổi dữ liệu cũ; báo cáo tính trực tiếp từ các bảng hiện có nên luôn khớp
  với dữ liệu thật, đổi lại chi phí truy vấn tăng theo số sinh viên.
