# Tài Liệu Tiếng Việt - Phenikaa Calendar Exporter

Chào mừng bạn đến với trung tâm tài liệu tiếng Việt của dự án **Phenikaa Calendar Exporter**!

Dự án này cung cấp bộ công cụ giúp sinh viên và giảng viên Trường Đại học Phenikaa trích xuất thời khóa biểu học tập và lịch thi từ cổng thông tin sinh viên (`qldtbeta.phenikaa-uni.edu.vn`) và đồng bộ trực tiếp vào các ứng dụng lịch phổ biến (Google Calendar, Apple Calendar, Outlook) cũng như xuất ra file Excel.

---

## 📚 Mục Lục Tài Liệu

### 👤 Dành Cho Người Dùng (Sinh viên & Giảng viên)
Tài liệu hướng dẫn trực quan, dễ hiểu, không yêu cầu kiến thức lập trình:

1. **[Bắt Đầu Nhanh](user/getting-started.md)**  
   Giới thiệu công cụ, các lợi ích nổi bật và cách chọn phương pháp phù hợp nhất với bạn.
2. **[Hướng Dẫn Cổng Web & Bảng Điều Khiển](user/web-portal.md)**  
   Cách tải lịch nhanh chỉ bằng một cú nhấp chuột hoặc kết nối tài khoản để tự động cập nhật.
3. **[Đồng Bộ Tự Động Sang Google Calendar](user/google-calendar-sync.md)**  
   Thiết lập đồng bộ lịch học và lịch thi một chiều vào lịch riêng biệt trên Google Calendar.
4. **[Nhập Lịch Vào Điện Thoại & Máy Tính](user/importing-calendars.md)**  
   Cách thêm file `.ics` vào ứng dụng Lịch trên iPhone/iPad, điện thoại Android, Mac và Outlook.
5. **[Tìm Hiểu Các File Xuất Ra](user/exports-and-formats.md)**  
   Ý nghĩa các cột trong bảng tính Excel (`.xlsx`), file lịch (`.ics`) và dữ liệu gốc (`.json`).

---

### 💻 Dành Cho Lập Trình Viên & Quản Trị Hệ Thống
Tài liệu kỹ thuật chuyên sâu về cấu trúc mã nguồn, cơ chế giải mã và triển khai máy chủ:

1. **[Kiến Trúc Hệ Thống](developer/architecture.md)**  
   Mô hình kiến trúc tổng quan, luồng dữ liệu, phân tầng giữa công cụ CLI và máy chủ Web.
2. **[Tham Chiếu Dòng Lệnh (CLI)](developer/cli-reference.md)**  
   Toàn bộ cờ lệnh, phương thức xác thực, định dạng ngày tháng và ví dụ tự động hóa.
3. **[Cơ Chế Xác Thực & Phân Tích Nội Bộ](developer/authentication-internals.md)**  
   Giải mã thuật toán XOR, trích xuất mã `AXYZCLRVN`, thu thập token bằng Playwright.
4. **[Giao Thức Kết Nối API Phenikaa](developer/api-protocol.md)**  
   Đặc tả chi tiết các endpoint nội bộ, thuật toán mã hóa payload (`AE`/`AD`) và cấu trúc JSON.
5. **[Hướng Dẫn Triển Khai Máy Chủ & Docker](developer/server-deployment.md)**  
   Cấu hình Docker, tích hợp Google OAuth / OIDC, quản lý khóa mã hóa Fernet và lưu trữ dữ liệu.
6. **[Kiểm Thử & Đóng Góp Mã Nguồn](developer/testing-and-contributing.md)**  
   Cách chạy bộ kiểm thử tự động (unit test), quy chuẩn mã nguồn và quy trình đóng góp.

---

### ❓ Xử Lý Sự Cố & Câu Hỏi Thường Gặp
- **[Cẩm Nang Xử Lý Sự Cố](troubleshooting.md)**  
  Hướng dẫn khắc phục các lỗi phổ biến (HTTP 401 hết hạn phiên, không tải được lịch, lệch múi giờ, lỗi Playwright).
