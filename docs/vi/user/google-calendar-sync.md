# Tự Động Đồng Bộ Sang Google Calendar

Tính năng đồng bộ tự động với Google Calendar giúp bạn luôn nắm bắt chính xác lịch học và lịch thi ngay trên điện thoại, máy tính bảng và đồng hồ thông minh mà không cần nhập thủ công.

---

## 🌟 Tại Sao Nên Đồng Bộ Lịch Sang Google Calendar?

- 🔔 **Nhắc giờ học thông minh**: Nhận thông báo trước mỗi tiết học hoặc buổi thi từ 15-30 phút trên điện thoại và smartwatch.
- 🔄 **Tự động cập nhật khi có thay đổi**: Khi nhà trường đổi phòng học, đổi giảng viên hoặc xếp lịch học bù, hệ thống sẽ tự động cập nhật sự kiện trên Google Calendar của bạn.
- 🛡️ **Tuyệt đối an toàn cho lịch cá nhân**: Hệ thống chỉ thao tác trong một lịch riêng biệt mang tên **`Phenikaa Learning Calendar`**. Toàn bộ lịch cá nhân, công việc, sinh nhật của bạn hoàn toàn không bị ảnh hưởng!
- 📱 **Hỗ trợ mọi thiết bị**: Xem được trên ứng dụng Google Calendar trên Android, iPhone, iPad, macOS và nền tảng Web.

---

## ⚙️ Cơ Chế Hoạt Động

```
┌─────────────────────────┐          ┌─────────────────────────┐
│ Cổng Đào Tạo Phenikaa   │          │  Máy Chủ Đồng Bộ        │
│ qldtbeta.phenikaa-uni...│ ───────► │  (Chạy ngầm định kỳ)    │
└─────────────────────────┘          └────────────┬────────────┘
                                                  │
                                                  │ Đồng bộ 1 chiều
                                                  ▼
                                     ┌─────────────────────────┐
                                     │     Google Calendar     │
                                     │ "Phenikaa Learning Cal" │
                                     └─────────────────────────┘
```

Đồng bộ diễn ra **hoàn toàn một chiều** (từ Cổng đào tạo trường sang Google):
- **Buổi học mới**: Tự động được thêm vào lịch.
- **Thay đổi thông tin**: Nếu trường đổi giờ, đổi phòng hoặc đổi thầy cô, sự kiện trên lịch sẽ được cập nhật lại theo đúng thông tin mới nhất.
- **Buổi học bị hủy**: Nếu một buổi học bị xóa khỏi cổng trường, sự kiện tương ứng trên Google Calendar sẽ được gỡ bỏ gọn gàng.
- **Lịch cá nhân của bạn**: Ứng dụng **không có quyền** đọc hay thay đổi bất kỳ lịch cá nhân nào khác của bạn.

---

## 📝 Hướng Dẫn Cài Đặt

### Trường Hợp 1: Máy chủ dùng chế độ "Đăng nhập bằng Google"
Đây là cách thiết lập nhanh và tiện lợi nhất:
1. Tại trang đăng nhập của web, nhấn **Sign in with Google** (Đăng nhập với Google).
2. Khi Google hỏi cấp quyền, bạn đồng ý cho phép ứng dụng tạo và quản lý lịch học.
3. Chuyển sang Dashboard và hoàn tất **Kết nối tài khoản Phenikaa**.
4. Xong! Hệ thống sẽ tự động tạo lịch **`Phenikaa Learning Calendar`** và đồng bộ ngay các buổi học vào tài khoản Google bạn vừa đăng nhập.

### Trường Hợp 2: Máy chủ dùng hệ thống xác thực riêng (OIDC/SSO)
1. Đăng nhập vào Dashboard bằng tài khoản được cấp.
2. Tại mục **Google Calendar**, nhấn nút **Kết nối Google Calendar** (Connect Google).
3. Trình duyệt chuyển sang trang ủy quyền của Google: Bạn chọn tài khoản Google cá nhân mà bạn muốn nhận lịch.
4. Kiểm tra quyền hạn yêu cầu:
   - Quyền hạn: `https://www.googleapis.com/auth/calendar.app.created` (Quyền này chỉ cho phép ứng dụng quản lý lịch do chính nó tạo ra, hoàn toàn không xem được lịch cá nhân của bạn).
5. Nhấn **Tiếp tục / Cho phép**.
6. Dashboard sẽ báo trạng thái **Đã kết nối** và bắt đầu đợt đồng bộ đầu tiên.

---

## 💡 Quản Lý Lịch Trên Google Calendar

### Xem Lịch Trên Điện Thoại
Mở ứng dụng Google Calendar trên điện thoại. Ở thanh menu bên trái, dưới mục **"Lịch của tôi"**, bạn sẽ thấy xuất hiện:
- 📅 **Phenikaa Learning Calendar**
Bạn có thể tùy chỉnh màu sắc (ví dụ: đổi sang màu xanh dương Phenikaa), bật/tắt hiển thị hoặc điều chỉnh thời gian rung chuông nhắc nhở.

### Tần Suất Cập Nhật
- Máy chủ sẽ tự động quét cổng đào tạo định kỳ mỗi 24 giờ (hoặc theo cấu hình của người quản trị).
- Nếu bạn vừa đổi môn hoặc có thông báo đổi lịch gấp trên trường, hãy vào Dashboard và bấm nút **Đồng bộ ngay (Sync Now)** để cập nhật ngay lập tức.

### Tạm Dừng & Hủy Kết Nối
- **Tạm dừng**: Khi vào kỳ nghỉ hè, bạn có thể bấm **Tạm dừng đồng bộ (Pause)**. Các sự kiện cũ vẫn được giữ nguyên trên điện thoại.
- **Hủy kết nối**: Khi muốn ngắt hẳn liên kết, bấm **Ngắt kết nối Google (Disconnect)**. Hệ thống sẽ thu hồi mã truy cập từ Google và ngừng hoàn toàn việc cập nhật.
