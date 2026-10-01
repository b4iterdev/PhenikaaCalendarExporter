# Tìm Hiểu Các File Xuất Ra & Cấu Trúc Dữ Liệu

Mỗi lần thực hiện xuất lịch, **Phenikaa Calendar Exporter** sẽ tạo ra 3 tệp tin với các định dạng chuyên biệt. Tài liệu này giải thích chi tiết ý nghĩa và mục đích sử dụng của từng tệp tin.

---

## 1. Bảng Tính Microsoft Excel (`.xlsx`)

Tệp Excel được thiết kế tối ưu cho việc in ấn, xem trực quan trên máy tính hoặc theo dõi chuyên cần học tập của bạn.

### Trang 1: `Calendar` (Danh sách chi tiết toàn bộ buổi học và thi)
Dữ liệu được sắp xếp tuần tự theo trình tự thời gian từ ngày đầu tiên đến ngày cuối cùng:

| Tiêu Đề Cột | Ý Nghĩa | Ví Dụ |
|---|---|---|
| **Date** | Ngày diễn ra buổi học/thi (`dd/mm/yyyy`) | `15/09/2026` |
| **Weekday** | Thứ trong tuần bằng tiếng Việt | `Thứ Ba` |
| **Start** | Giờ bắt đầu tiết học (`hh:mm`) | `07:00` |
| **End** | Giờ kết thúc tiết học (`hh:mm`) | `09:25` |
| **Type** | Phân loại sự kiện (`Class` - Buổi học hoặc `Exam` - Lịch thi) | `Class` |
| **Course** | Tên học phần chính thức | `Lập trình mạng` |
| **Class section** | Mã lớp học phần được phân công | `CNTT_K15_01` |
| **Room / Online** | Giảng đường, phòng thí nghiệm hoặc phòng học ảo | `A2-304` |
| **Lecturer** | Họ tên giảng viên phụ trách đứng lớp | `TS. Nguyễn Văn A` |
| **Periods** | Tiết học theo quy chế của trường | `1-3` |
| **Session** | Buổi học trong ngày | `Sáng` |
| **Attendance** | Ghi chú chuyên cần hoặc yêu cầu điểm danh | `Điểm danh 80%` |
| **Event ID** | Mã số định danh duy nhất của buổi học trên cổng đào tạo | `1234567` |

#### Đặc Điểm Thiết Kế:
- 🎨 **Tô màu nổi bật lịch thi**: Các hàng thuộc diện thi kết thúc học phần (`Exam`) được bôi nền màu cam nhạt (`#FCE4D6`) giúp bạn không bao giờ bỏ sót lịch thi quan trọng.
- 📌 **Cố định dòng tiêu đề (Freeze Panes)**: Dòng tiêu đề màu xanh navy (`#17365D`) luôn nằm ở đầu trang khi bạn cuộn chuột qua hàng trăm buổi học.
- 🔍 **Bộ lọc thông minh (Auto-Filter)**: Dễ dàng bấm vào mũi tên ở tiêu đề để lọc xem riêng lịch của một môn học hay một giảng viên cụ thể.

### Trang 2: `Summary` (Bảng tổng hợp & Thống kê học kỳ)
Cung cấp bức tranh toàn cảnh về khối lượng học tập trong kỳ của bạn:
- **Khoảng thời gian (Date range)**: Ngày bắt đầu và kết thúc kỳ học.
- **Tổng số sự kiện (Total events)**: Tổng tất cả các buổi học và buổi thi.
- **Số buổi học trên lớp (Classes) vs Số buổi thi (Exams)**.
- **Thống kê theo từng môn học**: Bảng liệt kê chi tiết từng môn học trong kỳ và tổng số buổi học của môn đó.

---

## 2. Tệp Lịch Điện Tử iCalendar (`.ics`)

Tệp `.ics` được thiết kế theo đúng chuẩn quốc tế **RFC 5545**:

- **Khai báo múi giờ chuẩn**: Nhúng định nghĩa `VTIMEZONE` cố định cho múi giờ Việt Nam `Asia/Ho_Chi_Minh` (UTC+07:00).
- **Phân loại lịch thi rõ ràng**: Các buổi thi sẽ tự động được thêm tiền tố `Exam: ` trước tên môn học và gắn nhãn danh mục `CATEGORIES:EXAM`.
- **Nội dung sự kiện chi tiết**:
  ```text
  Class: CNTT_K15_01
  Lecturer: TS. Nguyễn Văn A
  Periods: 1-3
  Attendance: Điểm danh bắt buộc
  ```
- **Mã định danh duy nhất (UID)**: Mỗi buổi học có mã định danh `UID:1234567@phenikaa-calendar` giúp ứng dụng lịch trên điện thoại nhận diện và cập nhật sự kiện thay vì tạo ra các bản ghi trùng lặp.
- **Xử lý tiếng Việt hoàn hảo**: Chuỗi ký tự tiếng Việt UTF-8 được ngắt dòng chuẩn xác theo quy tắc 75 octet của RFC 5545, không bao giờ bị lỗi font hay vỡ chữ.

---

## 3. Tệp Dữ Liệu Chuẩn Hóa (`.json`)

Tệp `.json` chứa danh sách các bản ghi đối tượng đã được làm sạch trực tiếp từ API của trường. Đây là nguồn tài nguyên lý tưởng cho các bạn sinh viên ngành Công nghệ thông tin muốn tự xây dựng thêm các tiện ích cá nhân (như bot thông báo lịch học trên Discord/Telegram, widget hiển thị lịch trên Notion hay ứng dụng di động).

Ví dụ một bản ghi JSON:
```json
{
  "ID": "1234567",
  "NGAYHOC": "15/09/2026",
  "GIOBATDAU": 7,
  "PHUTBATDAU": 0,
  "GIOKETTHUC": 9,
  "PHUTKETTHUC": 25,
  "PHANLOAI": "LICHHOC",
  "TENHOCPHAN": "Lập trình mạng",
  "TENLOPHOCPHAN": "CNTT_K15_01",
  "TENPHONGHOC": "A2-304",
  "GIANGVIEN": "TS. Nguyễn Văn A",
  "TIETBATDAU": 1,
  "TIETKETTHUC": 3,
  "BUOIHOC": "Sáng",
  "THONGTINCHUYENCAN": ""
}
```
