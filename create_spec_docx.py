"""Sinh tài liệu DOCX đặc tả tính năng MiniLMS.

Nội dung bám theo cấu trúc file mẫu "Đặc tả tính năng đề xuất - LMS",
đối chiếu với mã nguồn thực tế trong repo.
"""

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY = "1F3864"
ACCENT = "2E74B5"
GRAY = "595959"
LIGHT = "EAF1FB"
ZEBRA = "F5F8FC"
BORDER = "C9D3E0"
FONT = "Times New Roman"

PAGE_W = 16.5  # cm, bề rộng vùng nội dung A4


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def set_run(run, size=12, bold=False, italic=False, color=None, name=FONT):
    run.font.name = name
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), name)


def shade(cell, fill):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_margins(table, top=60, bottom=60, left=90, right=90):
    tbl_pr = table._tbl.tblPr
    mar = OxmlElement("w:tblCellMar")
    for tag, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        node = OxmlElement(f"w:{tag}")
        node.set(qn("w:w"), str(val))
        node.set(qn("w:type"), "dxa")
        mar.append(node)
    tbl_pr.append(mar)


def set_table_borders(table, color=BORDER, size=4):
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:space"), "0")
        node.set(qn("w:color"), color)
        borders.append(node)
    tbl_pr.append(borders)


def set_table_layout(table, widths):
    tbl_pr = table._tbl.tblPr
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)
    tbl_w = OxmlElement("w:tblW")
    tbl_w.set(qn("w:w"), str(int(sum(widths) * 567)))
    tbl_w.set(qn("w:type"), "dxa")
    tbl_pr.append(tbl_w)
    for column, width in zip(table.columns, widths, strict=False):
        column.width = Cm(width)


def repeat_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def cant_split(row):
    tr_pr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:cantSplit")
    node.set(qn("w:val"), "true")
    tr_pr.append(node)


def write_cell(cell, text, size=9.5, bold=False, color=None, align=None):
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.0
    if align is not None:
        paragraph.alignment = align
    run = paragraph.add_run(text)
    set_run(run, size=size, bold=bold, color=color)


def add_table(
    doc,
    headers,
    rows,
    widths,
    size=9.5,
    bold_first=False,
    center_cols=(),
    header_size=9.5,
    pad=60,
):
    table = doc.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_layout(table, widths)
    set_table_borders(table)
    set_cell_margins(table, top=pad, bottom=pad)

    head_row = table.rows[0]
    repeat_header(head_row)
    cant_split(head_row)
    for index, text in enumerate(headers):
        cell = head_row.cells[index]
        write_cell(
            cell,
            text,
            size=header_size,
            bold=True,
            color="FFFFFF",
            align=WD_ALIGN_PARAGRAPH.CENTER,
        )
        shade(cell, NAVY)

    for row_index, values in enumerate(rows):
        row = table.add_row()
        cant_split(row)
        for col_index, text in enumerate(values):
            cell = row.cells[col_index]
            bold = bold_first and col_index == 0
            align = WD_ALIGN_PARAGRAPH.CENTER if col_index in center_cols else None
            write_cell(cell, text, size=size, bold=bold, align=align)
            if row_index % 2 == 1:
                shade(cell, ZEBRA)
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(6)
    return table


def add_bottom_border(paragraph, color=NAVY, size=8, space=4):
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color)
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def add_heading(doc, text, level=1):
    paragraph = doc.add_paragraph(style=f"Heading {level}")
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run(text)
    if level == 1:
        set_run(run, size=15, bold=True, color=NAVY)
        paragraph.paragraph_format.space_before = Pt(14)
        paragraph.paragraph_format.space_after = Pt(7)
        add_bottom_border(paragraph, color=NAVY, size=6)
    else:
        set_run(run, size=12.5, bold=True, color=ACCENT)
        paragraph.paragraph_format.space_before = Pt(10)
        paragraph.paragraph_format.space_after = Pt(4)
    return paragraph


def add_body(doc, text, size=11.5, italic=False, space_after=5, color=None, keep_next=False):
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    paragraph.paragraph_format.space_after = Pt(space_after)
    paragraph.paragraph_format.line_spacing = 1.2
    paragraph.paragraph_format.keep_with_next = keep_next
    run = paragraph.add_run(text)
    set_run(run, size=size, italic=italic, color=color)
    return paragraph


def add_bullet(doc, text, size=11):
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(2)
    paragraph.paragraph_format.line_spacing = 1.15
    run = paragraph.add_run(text)
    set_run(run, size=size)


def add_note(doc, text, label="Ghi chú: "):
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    set_table_layout(table, [PAGE_W])
    set_cell_margins(table, top=100, bottom=100, left=150, right=150)

    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        if edge == "left":
            node.set(qn("w:val"), "single")
            node.set(qn("w:sz"), "18")
            node.set(qn("w:color"), ACCENT)
        else:
            node.set(qn("w:val"), "nil")
        borders.append(node)
    tbl_pr.append(borders)

    cell = table.cell(0, 0)
    shade(cell, LIGHT)
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1.15
    label_run = paragraph.add_run(label)
    set_run(label_run, size=10.5, bold=True, color=NAVY)
    body_run = paragraph.add_run(text)
    set_run(body_run, size=10.5, color="203864")
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(6)


def add_page_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " PAGE "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, separate, text, end):
        run._r.append(node)
    set_run(run, size=9, color=GRAY)


def add_total_field(paragraph):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = " NUMPAGES "
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    text = OxmlElement("w:t")
    text.text = "1"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    for node in (begin, instr, separate, text, end):
        run._r.append(node)
    set_run(run, size=9, color=GRAY)


def configure_styles(doc):
    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11.5)
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rfonts.set(qn(attr), FONT)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.15

    for level in (1, 2):
        style = doc.styles[f"Heading {level}"]
        style.font.name = FONT
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(NAVY if level == 1 else ACCENT)
        style.font.size = Pt(15 if level == 1 else 12.5)
        style.font.italic = False


def setup_page(doc):
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(1.9)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.0)
    section.header_distance = Cm(1.0)
    section.footer_distance = Cm(0.9)
    section.different_first_page_header_footer = True
    return section


def setup_header_footer(section):
    header = section.header
    paragraph = header.paragraphs[0]
    paragraph.style = "Normal"
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(PAGE_W), WD_TAB_ALIGNMENT.RIGHT)
    left = paragraph.add_run("ĐẶC TẢ TÍNH NĂNG — MINILMS")
    set_run(left, size=8.5, bold=True, color=GRAY)
    right = paragraph.add_run("\tNHÓM G3 · 2026")
    set_run(right, size=8.5, color=GRAY)
    add_bottom_border(paragraph, color=BORDER, size=4, space=2)

    footer = section.footer
    paragraph = footer.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    prefix = paragraph.add_run("MiniLMS · Đặc tả tính năng · Trang ")
    set_run(prefix, size=9, color=GRAY)
    add_page_field(paragraph)
    middle = paragraph.add_run(" / ")
    set_run(middle, size=9, color=GRAY)
    add_total_field(paragraph)


# --------------------------------------------------------------------------
# Nội dung
# --------------------------------------------------------------------------

COMPONENTS = [
    (
        "CLIENT",
        "Tầng giao diện chạy trên trình duyệt: các trang HTML do máy chủ dựng sẵn (Jinja2) "
        "và các ứng dụng gọi REST API. Chịu trách nhiệm nhận dữ liệu đầu vào, hiển thị kết quả "
        "và gửi kèm CSRF token cho biểu mẫu.",
    ),
    (
        "SERVER",
        "Tầng xử lý nghiệp vụ viết bằng Flask 3, tổ chức theo blueprint và lớp service. "
        "Cung cấp REST API, dựng giao diện web và thực thi kiểm soát truy cập hai lớp "
        "(gate + service).",
    ),
    (
        "DATABASE",
        "PostgreSQL lưu trữ người dùng, khoá học, ghi danh, bài tập, bài nộp, câu hỏi và kết quả "
        "học tập. Truy cập bằng SQL thuần qua psycopg, mọi thao tác ghi đều nằm trong transaction.",
    ),
    (
        "LƯU TRỮ TỆP",
        "Thư mục trên máy chủ lưu ảnh đại diện, tài liệu bài giảng và tệp bài nộp. Tên tệp được "
        "sinh ngẫu nhiên; kiểm tra phần mở rộng, dung lượng và chống path traversal.",
    ),
    (
        "EMAIL",
        "Dịch vụ SMTP gửi email đặt lại mật khẩu, xác nhận ghi danh và thông báo lớp. "
        "Email được gửi bất đồng bộ qua transactional outbox, không chặn yêu cầu HTTP.",
    ),
    (
        "SESSION/TOKEN",
        "Cơ chế duy trì trạng thái xác thực: JWT Bearer cho REST API và cookie phiên HttpOnly "
        "kèm CSRF token cho giao diện web.",
    ),
    (
        "OUTBOX",
        "Bảng sự kiện bền vững (outbox_events) ghi cùng transaction với dữ liệu nghiệp vụ; "
        "bộ gửi (dispatcher) đọc bảng này để giao email theo cơ chế at-least-once.",
    ),
]

ROLES = [
    ("SV", "Sinh viên", "Học, nộp bài, làm bài kiểm tra; chỉ xem dữ liệu của mình."),
    ("GV", "Giảng viên", "Quản lý môn mình phụ trách: tài liệu, bài tập, bài kiểm tra, điểm."),
    ("QT", "Quản trị viên", "Quản lý người dùng, khoá học, duyệt yêu cầu mở môn, xem nhật ký."),
    ("Khách", "Người chưa đăng nhập", "Đăng ký, đăng nhập và dùng các trang công khai."),
]

FEATURE_WIDTHS = [3.4, 7.9, 1.9, 3.3]

SECTIONS = [
    {
        "title": "1. Quản lý tài khoản và xác thực",
        "intro": "Toàn bộ mật khẩu được băm bằng bcrypt trước khi lưu; hệ thống hỗ trợ cả JWT cho API "
        "và phiên cookie cho giao diện web.",
        "rows": [
            (
                "Đăng ký tài khoản",
                "Tạo tài khoản bằng email, họ tên và mật khẩu; email không được trùng; tài khoản mới "
                "mặc định có vai trò SV và nhận JWT ngay sau khi đăng ký.",
                "Khách",
                "CLIENT SERVER DATABASE SESSION/TOKEN",
            ),
            (
                "Đăng nhập",
                "Xác thực email/mật khẩu; cấp JWT (mặc định 15 phút) hoặc phiên cookie HttpOnly "
                "(30 ngày nếu chọn ghi nhớ). Sai 5 lần liên tiếp bị khoá tạm 15 phút.",
                "Tất cả",
                "CLIENT SERVER DATABASE SESSION/TOKEN",
            ),
            (
                "Đăng nhập OAuth",
                "Đăng nhập bằng Google hoặc GitHub theo luồng PKCE kèm tham số state; hệ thống không "
                "tự liên kết danh tính OAuth với tài khoản đã có cùng email.",
                "Khách",
                "CLIENT SERVER DATABASE SESSION/TOKEN",
            ),
            (
                "Đăng xuất",
                "Vô hiệu hoá mọi token phát trước thời điểm hiện tại của người dùng và xoá phiên "
                "đăng nhập hiện hành.",
                "Tất cả",
                "SERVER SESSION/TOKEN",
            ),
            (
                "Khôi phục mật khẩu",
                "Gửi liên kết đặt lại mật khẩu tới email đã đăng ký; token chỉ dùng một lần và "
                "hết hạn sau 30 phút.",
                "Tất cả",
                "SERVER DATABASE EMAIL",
            ),
            (
                "Đổi mật khẩu",
                "Yêu cầu xác nhận mật khẩu hiện tại, kiểm tra độ mạnh của mật khẩu mới, cập nhật "
                "giá trị băm và vô hiệu hoá token cũ.",
                "Tất cả",
                "SERVER DATABASE",
            ),
            (
                "Khoá / mở khoá tài khoản",
                "QT khoá hoặc mở khoá một tài khoản; tài khoản bị khoá không thể đăng nhập và mọi "
                "token cũ đều bị từ chối.",
                "QT",
                "CLIENT SERVER DATABASE SESSION/TOKEN",
            ),
        ],
    },
    {
        "title": "2. Hồ sơ người dùng",
        "intro": "Hồ sơ chỉ cho phép sửa các trường an toàn; email, vai trò và định danh không thể "
        "thay đổi qua API hồ sơ.",
        "rows": [
            (
                "Xem hồ sơ cá nhân",
                "Hiển thị họ tên, email, vai trò, giới thiệu và số điện thoại của người dùng hiện tại.",
                "Tất cả",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Cập nhật hồ sơ",
                "Chỉ cho sửa họ tên (tối đa 100 ký tự), giới thiệu (tối đa 500) và số điện thoại "
                "(tối đa 30); từ chối mọi trường khác.",
                "Tất cả",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Ảnh đại diện",
                "Tải lên ảnh png, jpg, jpeg, gif hoặc webp tối đa 2 MB; tệp được lưu với tên ngẫu "
                "nhiên và hiển thị qua đường dẫn riêng.",
                "Tất cả",
                "CLIENT SERVER DATABASE LƯU TRỮ TỆP",
            ),
            (
                "Xem hồ sơ thành viên",
                "Xem thông tin công khai của giảng viên và sinh viên trong cùng khoá học mà mình "
                "là thành viên.",
                "Tất cả",
                "CLIENT SERVER DATABASE",
            ),
        ],
    },
    {
        "title": "3. Quản lý khoá học",
        "intro": "Phạm vi hiển thị khoá học được giới hạn theo vai trò; giảng viên chỉ thấy môn mình "
        "phụ trách, sinh viên chỉ thấy môn đã ghi danh.",
        "rows": [
            (
                "Tra cứu khoá học",
                "Liệt kê khoá học, tìm theo tên (q) và lọc theo giảng viên; QT xem tất cả, GV chỉ "
                "xem môn mình phụ trách, SV chỉ xem môn đã ghi danh.",
                "Tất cả",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Tạo khoá học",
                "GV tạo khoá học do chính mình phụ trách; QT tạo khoá học và chỉ định giảng viên. "
                "Mã khoá học có dạng c_<uuid>.",
                "GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Cập nhật khoá học",
                "Đổi tên khoá học; GV phụ trách môn hoặc QT thực hiện thao tác này.",
                "GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Gỡ bỏ khoá học",
                "QT gỡ khoá học khỏi hệ thống; dữ liệu gắn với môn như ghi danh, bài tập, bài nộp, "
                "thông báo và diễn đàn được dọn theo.",
                "QT",
                "SERVER DATABASE",
            ),
            (
                "Yêu cầu mở môn",
                "GV gửi yêu cầu mở môn mới; QT duyệt (sinh khoá học) hoặc từ chối. Yêu cầu có "
                "trạng thái PENDING, APPROVED hoặc REJECTED.",
                "GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Ghi danh",
                "SV tự ghi danh bằng mã khoá học; GV/QT thêm hoặc xoá sinh viên khỏi lớp. Tự ghi "
                "danh sinh sự kiện gửi email xác nhận.",
                "SV, GV, QT",
                "CLIENT SERVER DATABASE EMAIL",
            ),
            (
                "Xem thành viên lớp",
                "Danh sách giảng viên và sinh viên của môn kèm thông tin công khai; chỉ thành viên "
                "hoặc người quản lý môn được xem.",
                "Tất cả",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Tài liệu bài giảng",
                "GV/QT tải lên tệp pdf, doc(x), ppt(x), txt, zip, rar, xlsx hoặc csv tối đa 20 MB; "
                "SV đã ghi danh được tải xuống; tên tệp được kiểm tra để chống path traversal.",
                "GV, SV, QT",
                "CLIENT SERVER DATABASE LƯU TRỮ TỆP",
            ),
        ],
    },
    {
        "title": "4. Bài tập và đánh giá",
        "intro": "Mỗi sinh viên có tối đa một bài nộp cho mỗi bài tập; việc nộp lại được xử lý theo "
        "hướng không tạo bản trùng.",
        "rows": [
            (
                "Tạo bài tập",
                "GV phụ trách môn hoặc QT tạo bài tập với tiêu đề, mô tả yêu cầu và thời hạn nộp.",
                "GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Nộp bài",
                "SV đã ghi danh nộp trước hạn bằng nội dung văn bản và/hoặc tệp tối đa 20 MB; "
                "hệ thống ghi nhận thời điểm nộp.",
                "SV",
                "CLIENT SERVER DATABASE LƯU TRỮ TỆP",
            ),
            (
                "Nộp lại bài",
                "Gửi lại đúng nội dung cũ trả về bài nộp hiện có (không tạo bản trùng); nội dung "
                "khác bị từ chối với lỗi 409.",
                "SV",
                "SERVER DATABASE",
            ),
            (
                "Truy xuất bài nộp",
                "SV chỉ xem bài của mình; GV xem bài của lớp mình phụ trách; QT xem toàn bộ; hỗ trợ "
                "tải tệp đính kèm.",
                "SV, GV, QT",
                "SERVER DATABASE LƯU TRỮ TỆP",
            ),
            (
                "Chấm điểm bài nộp",
                "GV/QT ghi điểm và nhận xét cho từng bài nộp; thao tác được ghi vào nhật ký.",
                "GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Tra cứu điểm",
                "SV xem điểm của chính mình; GV/QT xem bảng điểm của môn; dữ liệu trả theo từng "
                "sinh viên.",
                "SV, GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Sửa điểm",
                "GV phụ trách cập nhật điểm; endpoint lõi giữ hành vi last-write-wins và tăng "
                "version sau mỗi lần ghi.",
                "GV",
                "SERVER DATABASE",
            ),
            (
                "Sửa điểm có kiểm soát phiên bản",
                "Endpoint /v2 yêu cầu expectedVersion; nếu phiên bản đã đổi, trả 409 và không ghi "
                "đè; nhật ký ghi phiên bản cũ và mới.",
                "GV",
                "SERVER DATABASE",
            ),
        ],
    },
    {
        "title": "5. Bài kiểm tra trắc nghiệm",
        "intro": "Bài kiểm tra được chấm hoàn toàn trên máy chủ; đáp án đúng không được trả về cho "
        "sinh viên trong quá trình làm bài.",
        "rows": [
            (
                "Tạo bài kiểm tra",
                "GV/QT thiết lập tiêu đề, mô tả, thời lượng (phút), số lần làm tối đa (mặc định 1) "
                "và danh sách câu hỏi một đáp án đúng kèm điểm từng câu.",
                "GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Làm bài kiểm tra",
                "SV đã ghi danh bắt đầu lượt làm; hệ thống ghi thời điểm bắt đầu, giới hạn số lần "
                "làm và đếm thời gian theo thời lượng đã đặt.",
                "SV",
                "CLIENT SERVER DATABASE SESSION/TOKEN",
            ),
            (
                "Chấm điểm tự động",
                "Máy chủ đối chiếu câu trả lời với đáp án, tính điểm thang 10 và lưu lại câu trả "
                "lời cùng kết quả của từng lượt.",
                "—",
                "SERVER DATABASE",
            ),
            (
                "Kiểm soát lượt làm",
                "Bài đã nộp không được nộp lại (409); nộp sau thời lượng trả 409 TIME_EXPIRED; "
                "mỗi lượt chỉ có một lần nộp.",
                "SV",
                "SERVER DATABASE",
            ),
            (
                "Quản lý bài kiểm tra",
                "GV/QT xem danh sách bài kiểm tra và lượt làm của lớp; SV xem lượt làm của mình; "
                "GV/QT xoá bài kiểm tra.",
                "GV, SV, QT",
                "CLIENT SERVER DATABASE",
            ),
        ],
    },
    {
        "title": "6. Trao đổi và thông báo",
        "intro": "Thông báo lớp vừa hiển thị trên hệ thống vừa được gửi email; nội dung diễn đàn "
        "chỉ người tạo hoặc người quản lý môn được sửa, xoá.",
        "rows": [
            (
                "Đăng thông báo lớp",
                "GV/QT đăng thông báo tới toàn bộ lớp; thông báo hiển thị trên hệ thống và được "
                "gửi email cho sinh viên đã ghi danh.",
                "GV, QT",
                "CLIENT SERVER DATABASE EMAIL",
            ),
            (
                "Xem và xoá thông báo",
                "Thành viên lớp xem thông báo; GV/QT xoá thông báo khi cần.",
                "SV, GV, QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Diễn đàn khoá học",
                "Thành viên lớp tạo chủ đề và bình luận; người dùng chỉ sửa hoặc xoá nội dung của "
                "chính mình, GV/QT có quyền quản lý nội dung lớp.",
                "SV, GV, QT",
                "CLIENT SERVER DATABASE",
            ),
        ],
    },
    {
        "title": "7. Quản trị hệ thống",
        "intro": "Nhóm tính năng dành riêng cho QT, bao gồm quản lý người dùng, khoá học và nhật ký "
        "hoạt động.",
        "rows": [
            (
                "Quản lý người dùng",
                "QT tra cứu danh sách người dùng, đổi vai trò và khoá/mở khoá tài khoản; thay đổi "
                "vai trò làm vô hiệu token cũ.",
                "QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Quản lý khoá học",
                "QT tra cứu toàn bộ khoá học và gỡ bỏ khoá học khỏi hệ thống.",
                "QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Duyệt yêu cầu mở môn",
                "QT xem danh sách yêu cầu và duyệt hoặc từ chối; yêu cầu đã xử lý không thể xử lý "
                "lại (409).",
                "QT",
                "CLIENT SERVER DATABASE",
            ),
            (
                "Nhật ký hoạt động",
                "Ghi sự kiện quan trọng ra tệp JSONL: đăng nhập/đăng xuất, đổi điểm, ghi danh, bài "
                "nộp, bài kiểm tra, thông báo và thao tác quản trị; không ghi mật khẩu hay token.",
                "QT",
                "SERVER DATABASE",
            ),
            (
                "Cấu hình hệ thống",
                "Cấu hình qua biến môi trường: JWT_SECRET, DATABASE_URL, SMTP_*, OUTBOX_* và thư "
                "mục lưu tệp; thiếu JWT_SECRET thì ứng dụng không khởi động.",
                "QT",
                "SERVER",
            ),
        ],
    },
]

UI_ROWS = [
    ("Trang chủ, đăng nhập, đăng ký", "/, /login, /register", "Khách"),
    ("Quên và đặt lại mật khẩu", "/forgot-password, /reset-password?token=...", "Khách"),
    ("Đăng nhập OAuth", "/oauth/<provider>", "Khách"),
    ("Tài khoản, hồ sơ, ảnh đại diện", "/account", "Tất cả"),
    ("Danh sách và tìm kiếm khoá học", "/ui/courses", "Tất cả"),
    ("Chi tiết khoá học", "/ui/courses/<id>", "Thành viên lớp"),
    ("Bài tập và nộp bài", "/ui/assignments/<id>", "Thành viên lớp"),
    ("Bài kiểm tra và làm bài", "/ui/quizzes/<id>", "Thành viên lớp"),
    ("Thảo luận", "/ui/threads/<id>", "Thành viên lớp"),
    ("Quản trị người dùng và nhật ký", "/ui/admin", "QT"),
]

API_ROWS = [
    (
        "Xác thực",
        "POST /auth/login, /auth/register, /auth/logout, /auth/forgot-password, "
        "/auth/reset-password; GET /me",
    ),
    ("Hồ sơ", "GET/PUT /users/me; POST /users/me/avatar; GET /users/<id>/avatar"),
    ("Khoá học", "GET/POST /courses; GET/PATCH/DELETE /courses/<id>; GET /courses/<id>/members"),
    (
        "Yêu cầu mở môn",
        "POST/GET /course-requests; POST /course-requests/<id>/approve hoặc /reject",
    ),
    (
        "Ghi danh",
        "POST /me/enrollments; POST/DELETE /courses/<id>/enrollments[/<student_id>]",
    ),
    ("Tài liệu", "POST/GET /courses/<id>/materials; GET /materials/<id>/download"),
    (
        "Bài tập",
        "POST/GET /courses/<id>/assignments; POST /assignments/<id>/submissions; "
        "POST /submissions/<id>/grade",
    ),
    (
        "Điểm",
        "GET/PUT /courses/<id>/grades[/<student_id>]; GET/PUT .../v2; GET /me/grades",
    ),
    (
        "Bài kiểm tra",
        "POST/GET /courses/<id>/quizzes; POST /quizzes/<id>/attempts; "
        "POST /quizzes/<id>/attempts/<attempt_id>/submit",
    ),
    (
        "Diễn đàn",
        "POST/GET /courses/<id>/announcements|threads; PATCH/DELETE /threads|/comments",
    ),
    (
        "Quản trị",
        "GET /admin/users; PATCH /admin/users/<id>/role; POST /admin/users/<id>/lock|unlock; "
        "GET /admin/audit",
    ),
    ("Tài liệu API", "GET /api/docs/openapi.yaml (đặc tả OpenAPI 3.0)"),
]

COMPARE_ROWS = [
    (
        "1. Quản lý tài khoản và xác thực",
        "Có, mở rộng",
        "Thêm đăng nhập OAuth Google/GitHub, khoá tài khoản và khoá tạm sau 5 lần sai; "
        "đăng xuất vô hiệu hoá token cũ.",
    ),
    (
        "2. Hồ sơ người dùng",
        "Có",
        "Bổ sung giới thiệu và số điện thoại; ảnh đại diện giới hạn 2 MB và kiểm tra định dạng.",
    ),
    (
        "3. Quản lý khoá học",
        "Có, mở rộng",
        "Thêm yêu cầu mở môn, phân quyền dữ liệu theo môn và gỡ bỏ khoá học.",
    ),
    (
        "4. Bài tập và đánh giá",
        "Có, mở rộng",
        "Thêm chống nộp trùng và optimistic locking cho thao tác sửa điểm qua endpoint /v2.",
    ),
    (
        "5. Bài kiểm tra trắc nghiệm",
        "Có",
        "Bổ sung thời lượng làm bài, số lần làm tối đa, chặn nộp lại và chặn nộp quá hạn.",
    ),
    (
        "6. Trao đổi và thông báo",
        "Có",
        "Thông báo gửi email qua outbox; diễn đàn cho phép sửa/xoá nội dung của chính mình.",
    ),
    (
        "7. Quản trị hệ thống",
        "Có, mở rộng",
        "Thêm duyệt yêu cầu mở môn, nhật ký JSONL và API đọc nhật ký.",
    ),
    (
        "8. REST API và tài liệu OpenAPI",
        "Có",
        "API JSON đầy đủ, tài liệu OpenAPI 3.0; bổ sung giao diện web dựng sẵn bằng Jinja2.",
    ),
]

ERROR_ROWS = [
    ("400", "VALIDATION_ERROR", "Dữ liệu đầu vào không hợp lệ hoặc sai định dạng."),
    ("401", "UNAUTHENTICATED", "Thiếu token, token sai hoặc đã bị vô hiệu hoá."),
    ("401", "INVALID_CREDENTIALS", "Sai email hoặc mật khẩu."),
    ("403", "FORBIDDEN", "Không đủ quyền truy cập tài nguyên."),
    ("404", "NOT_FOUND", "Không tìm thấy tài nguyên."),
    (
        "409",
        "CONFLICT",
        "Xung đột dữ liệu: trùng ghi danh, nộp bài khác nội dung, phiên bản đã đổi hoặc "
        "yêu cầu đã được xử lý.",
    ),
    ("409", "TIME_EXPIRED", "Nộp bài kiểm tra khi đã quá thời lượng."),
    ("429", "ACCOUNT_LOCKED", "Tài khoản bị QT khoá hoặc tạm khoá do sai mật khẩu."),
    ("503", "MAIL_DELIVERY_FAILED", "Không gửi được email đặt lại mật khẩu."),
    ("500", "INTERNAL_ERROR", "Lỗi không mong đợi phía máy chủ."),
]


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def build():
    doc = Document()
    configure_styles(doc)
    section = setup_page(doc)
    setup_header_footer(section)

    cp = doc.core_properties
    cp.title = "Đặc tả tính năng MiniLMS"
    cp.subject = "Đặc tả tính năng đề xuất - Hệ thống quản lý học tập MiniLMS"
    cp.author = "Nhóm G3"
    cp.keywords = "MiniLMS, LMS, đặc tả tính năng, Flask, PostgreSQL"
    cp.comments = "Biên soạn dựa trên đặc tả mẫu, đối chiếu với mã nguồn MiniLMS."

    # ---------------- Cover ----------------
    top = doc.add_paragraph()
    top.paragraph_format.space_before = Pt(10)
    top.paragraph_format.space_after = Pt(2)
    run = top.add_run("MINILMS  ·  NHÓM G3")
    set_run(run, size=10, bold=True, color=ACCENT)

    eyebrow = doc.add_paragraph()
    eyebrow.paragraph_format.space_before = Pt(36)
    eyebrow.paragraph_format.space_after = Pt(2)
    run = eyebrow.add_run("TÀI LIỆU DỰ ÁN")
    set_run(run, size=11, bold=True, color=GRAY)

    title = doc.add_paragraph()
    title.paragraph_format.space_before = Pt(0)
    title.paragraph_format.space_after = Pt(2)
    run = title.add_run("ĐẶC TẢ TÍNH NĂNG")
    set_run(run, size=30, bold=True, color=NAVY)

    subtitle = doc.add_paragraph()
    subtitle.paragraph_format.space_after = Pt(10)
    run = subtitle.add_run("Hệ thống quản lý học tập MiniLMS")
    set_run(run, size=17, bold=False, color=ACCENT)

    line = doc.add_paragraph()
    line.paragraph_format.space_before = Pt(2)
    line.paragraph_format.space_after = Pt(14)
    add_bottom_border(line, color=NAVY, size=12, space=1)

    description = doc.add_paragraph()
    description.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    description.paragraph_format.space_after = Pt(12)
    run = description.add_run(
        "Tài liệu mô tả các tính năng của hệ thống MiniLMS theo từng nhóm chức năng, "
        "vai trò sử dụng và thành phần hệ thống liên quan. Nội dung được biên soạn dựa trên "
        "đặc tả tính năng mẫu và đối chiếu trực tiếp với mã nguồn của dự án."
    )
    set_run(run, size=11.5, color="333333")

    meta = doc.add_table(rows=0, cols=2)
    meta.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta.autofit = False
    set_table_layout(meta, [4.2, 9.0])
    set_table_borders(meta, color="D6DCE5", size=4)
    set_cell_margins(meta, top=80, bottom=80, left=120, right=120)
    meta_rows = [
        ("Dự án", "MiniLMS — Hệ thống quản lý học tập"),
        ("Nhóm thực hiện", "Nhóm G3"),
        ("Phiên bản", "1.0"),
        ("Ngày biên soạn", "08/11/2026"),
        ("Nguồn tham khảo", "Đặc tả tính năng LMS (mẫu) và mã nguồn MiniLMS"),
        ("Trạng thái", "Bản đề xuất"),
    ]
    for label, value in meta_rows:
        row = meta.add_row()
        cant_split(row)
        write_cell(row.cells[0], label, size=10, bold=True, color=NAVY)
        shade(row.cells[0], LIGHT)
        write_cell(row.cells[1], value, size=10)

    note = doc.add_paragraph()
    note.paragraph_format.space_before = Pt(18)
    note.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    run = note.add_run(
        "Ghi chú phạm vi: tài liệu chỉ mô tả các tính năng đã có trong mã nguồn. "
        "Các điểm khác biệt so với đặc tả mẫu được tổng hợp ở Phụ lục A."
    )
    set_run(run, size=9, italic=True, color=GRAY)

    doc.add_page_break()

    # ---------------- Mục lục ----------------
    add_heading(doc, "Mục lục", level=1)
    toc_entries = [
        "Các thành phần hệ thống",
        "Vai trò người dùng",
        "1. Quản lý tài khoản và xác thực",
        "2. Hồ sơ người dùng",
        "3. Quản lý khoá học",
        "4. Bài tập và đánh giá",
        "5. Bài kiểm tra trắc nghiệm",
        "6. Trao đổi và thông báo",
        "7. Quản trị hệ thống",
        "8. Giao diện web",
        "9. REST API và tài liệu",
        "10. Đặc điểm kỹ thuật nổi bật",
        "Phụ lục A. Đối chiếu với đặc tả mẫu",
        "Phụ lục B. Quy ước lỗi",
    ]
    for entry in toc_entries:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.space_after = Pt(2)
        paragraph.paragraph_format.left_indent = Cm(0.4)
        run = paragraph.add_run(entry)
        set_run(run, size=11, color="222222")

    # ---------------- Thành phần ----------------
    add_heading(doc, "Các thành phần hệ thống", level=1)
    add_body(
        doc,
        "MiniLMS được tổ chức thành các thành phần độc lập theo trách nhiệm. Bảng dưới đây mô tả "
        "từng thành phần và công nghệ tương ứng trong mã nguồn.",
    )
    add_table(
        doc,
        ["Thành phần", "Mô tả"],
        COMPONENTS,
        [2.6, 13.9],
        size=9.5,
        bold_first=True,
        pad=40,
    )

    # ---------------- Vai trò ----------------
    add_heading(doc, "Vai trò người dùng", level=1)
    add_body(
        doc,
        "Hệ thống phân quyền theo bốn nhóm vai trò. Mã SV, GV, QT được dùng thống nhất trong toàn "
        "bộ tài liệu; Khách là người chưa đăng nhập.",
        keep_next=True,
    )
    add_table(
        doc,
        ["Mã", "Vai trò", "Mô tả"],
        ROLES,
        [1.6, 3.4, 11.5],
        size=9.5,
        bold_first=True,
        center_cols=(0,),
        pad=40,
    )

    # ---------------- Các nhóm tính năng ----------------
    for feature_section in SECTIONS:
        add_heading(doc, feature_section["title"], level=1)
        add_body(doc, feature_section["intro"], keep_next=True)
        add_table(
            doc,
            ["Tính năng", "Mô tả", "Vai trò", "Thành phần liên quan"],
            feature_section["rows"],
            FEATURE_WIDTHS,
            size=9.5,
            bold_first=True,
            center_cols=(2,),
        )

    add_note(
        doc,
        "Bảng điểm và bài kiểm tra là hai luồng độc lập: điểm bài tập được chấm thủ công, "
        "điểm bài kiểm tra trắc nghiệm do máy chủ tính tự động. Cả hai đều ghi nhật ký khi thay đổi.",
    )

    # ---------------- Giao diện web ----------------
    add_heading(doc, "8. Giao diện web", level=1)
    add_body(
        doc,
        "Ngoài REST API, hệ thống cung cấp giao diện web dựng sẵn bằng Jinja2. Biểu mẫu web dùng "
        "cookie phiên HttpOnly và CSRF token; người dùng chưa đăng nhập được chuyển về trang đăng nhập.",
        keep_next=True,
    )
    add_table(
        doc,
        ["Trang", "Đường dẫn", "Vai trò"],
        UI_ROWS,
        [5.0, 6.5, 5.0],
        size=9.5,
        bold_first=True,
        center_cols=(2,),
    )
    add_note(
        doc,
        "Trang chi tiết khoá học tổng hợp thành viên, tài liệu, thông báo, bài tập, bài kiểm tra và "
        "diễn đàn trong cùng một màn hình; quyền truy cập được kiểm tra lại ở lớp service.",
    )

    # ---------------- REST API ----------------
    add_heading(doc, "9. REST API và tài liệu", level=1)
    add_body(
        doc,
        "REST API dùng JSON, xác thực bằng Bearer JWT và trả lỗi theo dạng {\"error\": \"<CODE>\"}. "
        "Đặc tả OpenAPI 3.0 được phục vụ tại /api/docs/openapi.yaml.",
        keep_next=True,
    )
    add_table(
        doc,
        ["Nhóm chức năng", "Endpoint tiêu biểu"],
        API_ROWS,
        [3.2, 13.3],
        size=9.5,
        bold_first=True,
    )
    add_note(
        doc,
        "Ngoài HTTP API, hệ thống có CLI vận hành outbox: flask --app app outbox drain [--limit N] "
        "và flask --app app outbox status.",
    )

    # ---------------- Kỹ thuật nổi bật ----------------
    add_heading(doc, "10. Đặc điểm kỹ thuật nổi bật", level=1)
    add_body(
        doc,
        "Ba đặc điểm dưới đây được cài đặt trực tiếp trong mã nguồn và là phần khác biệt rõ nhất so "
        "với đặc tả mẫu.",
    )

    add_heading(doc, "10.1. Optimistic locking cho thao tác sửa điểm", level=2)
    add_body(
        doc,
        "Cột version trên bảng ghi danh được tăng sau mỗi lần ghi điểm. Endpoint /v2 yêu cầu "
        "expectedVersion và thực hiện một câu UPDATE có điều kiện; nếu phiên bản đã thay đổi, hệ "
        "thống trả 409 thay vì ghi đè.",
    )
    add_bullet(doc, "Phát hiện ghi đè giữa hai giảng viên hoặc hai tab của cùng một người.")
    add_bullet(doc, "Endpoint lõi giữ nguyên hợp đồng cũ nhưng vẫn tăng version để client /v2 nhận biết.")
    add_bullet(doc, "Nhật ký ghi oldScore, newScore và version của lần cập nhật.")

    add_heading(doc, "10.2. Transactional outbox cho email", level=2)
    add_body(
        doc,
        "Khi sinh viên tự ghi danh hoặc giảng viên đăng thông báo, dữ liệu nghiệp vụ và sự kiện "
        "được ghi trong cùng một transaction vào bảng outbox_events. Bộ gửi đọc sự kiện và giao "
        "email theo cơ chế at-least-once.",
    )
    add_bullet(doc, "Trạng thái sự kiện: PENDING → SENDING → SENT, hoặc DEAD sau số lần thử tối đa.")
    add_bullet(doc, "Sự kiện SENDING quá thời hạn thuê (lease) được đưa về PENDING để khôi phục sau sự cố.")
    add_bullet(doc, "Message-ID ổn định theo mã sự kiện giúp phía nhận chống trùng email.")

    add_heading(doc, "10.3. Kiểm soát truy cập và bảo mật", level=2)
    add_bullet(doc, "JWT Bearer cho API, cookie HttpOnly và CSRF token cho biểu mẫu web.")
    add_bullet(doc, "Kiểm tra quyền hai lớp: gate trước khi vào route và service trước khi thao tác dữ liệu.")
    add_bullet(doc, "Mật khẩu băm bcrypt; khoá tạm sau 5 lần đăng nhập sai; QT có thể khoá tài khoản.")
    add_bullet(doc, "Tệp tải lên được giới hạn định dạng, dung lượng và kiểm tra path traversal.")
    add_bullet(doc, "Nhật ký JSONL không chứa mật khẩu, token hay nội dung email.")

    # ---------------- Phụ lục A ----------------
    add_heading(doc, "Phụ lục A. Đối chiếu với đặc tả mẫu", level=1)
    add_body(
        doc,
        "Đặc tả mẫu gồm tám nhóm tính năng. MiniLMS đáp ứng đủ cả tám nhóm và mở rộng thêm một số "
        "tính năng kỹ thuật; bảng dưới đây tổng hợp mức độ tương ứng và điểm khác biệt.",
    )
    add_table(
        doc,
        ["Nhóm trong đặc tả mẫu", "Trong MiniLMS", "Ghi chú / khác biệt"],
        COMPARE_ROWS,
        [4.3, 3.2, 9.0],
        size=9.5,
        bold_first=True,
        center_cols=(1,),
    )

    add_heading(doc, "Bổ sung ngoài đặc tả mẫu", level=2)
    add_bullet(doc, "Đăng nhập OAuth Google/GitHub với PKCE và state.")
    add_bullet(doc, "Khoá/mở khoá tài khoản và khoá tạm khi đăng nhập sai nhiều lần.")
    add_bullet(doc, "Quy trình yêu cầu mở môn và duyệt/từ chối của QT.")
    add_bullet(doc, "Optimistic locking cho điểm và transactional outbox cho email.")
    add_bullet(doc, "Giao diện web dựng sẵn song song với REST API.")
    add_note(
        doc,
        "Khác biệt về phạm vi dữ liệu: đặc tả mẫu ghi \"Tất cả\" có thể tra cứu mọi khoá học, "
        "trong khi MiniLMS giới hạn GV chỉ thấy môn mình phụ trách và SV chỉ thấy môn đã ghi danh. "
        "Đây là chủ đích bảo mật của dự án, không phải thiếu sót.",
    )

    # ---------------- Phụ lục B ----------------
    doc.add_page_break()
    add_heading(doc, "Phụ lục B. Quy ước lỗi", level=1)
    add_body(
        doc,
        "Mọi phản hồi lỗi của REST API có dạng {\"error\": \"<CODE>\"} kèm mã HTTP tương ứng. "
        "Bảng dưới đây liệt kê các mã lỗi đang dùng trong hệ thống.",
    )
    add_table(
        doc,
        ["HTTP", "Mã lỗi", "Ý nghĩa"],
        ERROR_ROWS,
        [2.0, 5.0, 9.5],
        size=10,
        bold_first=False,
        center_cols=(0,),
    )
    add_note(
        doc,
        "Lỗi 403 được ghi vào nhật ký với hành động ACCESS_DENIED; lỗi xác thực không ghi "
        "mật khẩu hay token vào nhật ký.",
    )

    output = "dac_ta_tinh_nang_miniLMS.docx"
    doc.save(output)
    print(f"saved: {output}")


if __name__ == "__main__":
    build()
