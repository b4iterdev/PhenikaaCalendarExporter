# Hướng Dẫn Bắt Đầu Nhanh

Chào mừng bạn đến với **Phenikaa Calendar Exporter**! Đây là công cụ tiện ích giúp các bạn sinh viên và thầy cô giảng viên Trường Đại học Phenikaa dễ dàng chuyển toàn bộ thời khóa biểu học tập và lịch thi từ cổng đào tạo vào ứng dụng lịch trên điện thoại, máy tính.

---

## 🎯 Tại Sao Bạn Nên Dùng Công Cụ Này?

Thông thường, việc theo dõi lịch học tại trường yêu cầu bạn phải thường xuyên truy cập cổng đào tạo `qldtbeta.phenikaa-uni.edu.vn`. Trên màn hình điện thoại, giao diện bảng biểu khá nhỏ và khó tra cứu, còn việc nhập tay từng buổi học vào lịch thì tốn rất nhiều thời gian.

Với công cụ này:
- ⚡ **Xuất toàn bộ lịch kỳ học trong vài giây**: Tự động lấy lịch học và lịch thi của cả học kỳ chỉ sau một lần thao tác.
- ⏰ **Nhắc nhở tự động trước mỗi tiết học/thi**: Nhận thông báo trước giờ học từ 15-30 phút ngay trên điện thoại hoặc đồng hồ thông minh (Apple Watch, Galaxy Watch).
- 📍 **Đầy đủ chi tiết từng buổi**: Mỗi sự kiện lịch đều ghi rõ phòng học, giảng viên phụ trách, lớp học phần, số tiết học và ghi chú chuyên cần.
- 🔒 **An toàn & bảo mật tuyệt đối**: Công cụ **hoàn toàn không lưu trữ** mật khẩu tài khoản trường của bạn.

---

## 🛠️ Chọn Cách Sử Dụng Phù Hợp Với Bạn

```
┌────────────────────────────────────────────────────────┐
│             Phenikaa Calendar Exporter                 │
└───────────────────────────┬────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
    [ Giao Diện Web ]               [ Dòng Lệnh CLI ]
   • Phù hợp với mọi người         • Dành cho bạn thích code
   • Bấm chuột trực quan           • Chạy qua Terminal / CMD
   • Tự động đồng bộ Google        • Xuất file trực tiếp máy cá nhân
   • Dùng được trên điện thoại     • Không cần cài đặt máy chủ
```

### Cách 1: Sử Dụng Giao Diện Web (Khuyên dùng)
Nếu câu lạc bộ, khoa hoặc trường của bạn đang chạy một máy chủ Phenikaa Calendar:
1. Bạn chỉ cần truy cập vào đường link website trên trình duyệt (điện thoại hoặc máy tính).
2. Chọn mục **Xuất lịch công khai** để tải nhanh file hoặc **Đăng nhập** để bật tính năng tự động đồng bộ sang Google Calendar.
3. 👉 Xem chi tiết tại: **[Hướng Dẫn Cổng Web & Bảng Điều Khiển](web-portal.md)**.

### Cách 2: Sử Dụng Dòng Lệnh CLI (Cho lập trình viên)
Nếu máy tính của bạn đã có cài Python và muốn tự chạy xuất file về máy cá nhân:
1. Clone dự án về máy và cài đặt thư viện cần thiết.
2. Chạy lệnh xuất lịch tự động mở cửa sổ đăng nhập trình duyệt.
3. 👉 Xem chi tiết tại: **[Tham Chiếu Dòng Lệnh (CLI)](../developer/cli-reference.md)**.

---

## 📦 Bạn Sẽ Nhận Được Những Gì?

Mỗi lần xuất lịch, hệ thống sẽ tạo ra 3 định dạng file chuyên dụng:

| Định Dạng | Ứng Dụng Phù Hợp | Mô Tả |
|---|---|---|
| **`.ics`** | Google Calendar, Apple Lịch, Outlook | File lịch tiêu chuẩn quốc tế. Nhập vào điện thoại là có ngay lịch học từng ngày kèm thông báo nhắc nhở. |
| **`.xlsx`** | Microsoft Excel, Google Sheets, In ấn | Bảng tính Excel đẹp mắt, có tô màu phân biệt buổi thi, cột lọc thông minh và trang tóm tắt số tiết theo môn. |
| **`.json`** | Lập trình viên, Bot Discord/Telegram | File dữ liệu có cấu trúc sạch, dùng để phát triển các ứng dụng phụ trợ tự động. |

👉 Tìm hiểu kỹ hơn tại: **[Tìm Hiểu Các File Xuất Ra](exports-and-formats.md)**.

---

## 🚀 Bước Tiếp Theo

- Muốn tải ngay file lịch học của mình? 👉 Xem **[Hướng Dẫn Cổng Web](web-portal.md)**.
- Muốn tự động đồng bộ sang điện thoại qua Google Calendar? 👉 Xem **[Đồng Bộ Google Calendar](google-calendar-sync.md)**.
- Đã tải được file `.ics` và muốn cài vào iPhone/Android? 👉 Xem **[Nhập Lịch Vào Điện Thoại](importing-calendars.md)**.
