# Cẩm Nang Xử Lý Sự Cố & Câu Hỏi Thường Gặp

Tài liệu này tổng hợp các vấn đề thường gặp trong quá trình sử dụng **Phenikaa Calendar Exporter** (ở cả chế độ dòng lệnh CLI và máy chủ web) kèm theo hướng dẫn khắc phục cụ thể.

---

## 1. Bảng Tra Cứu Sự Cố Nhanh

| Hiện Tượng | Nguyên Nhân Thường Gặp | Cách Xử Lý |
|---|---|---|
| **API trả về 0 sự kiện** | Khoảng ngày quá hẹp hoặc chưa tới kỳ học mới. | Mở rộng dải ngày bao trọn cả học kỳ (ví dụ: từ 01/08 đến 31/01 năm sau). |
| **Lỗi HTTP 401 / Hết hạn phiên** | Token đã hết hạn hoặc vừa đăng nhập trên thiết bị khác. | Mở cổng đào tạo đăng nhập lại để làm mới token hoặc cập nhật file `.auth.json`. |
| **Giờ học trên lịch bị lệch vài tiếng** | Ứng dụng lịch chưa đặt đúng múi giờ GMT+7. | Bật tính năng múi giờ trong ứng dụng lịch và chọn `Asia/Ho_Chi_Minh` (GMT+07:00). |
| **`playwright is required`** | Chưa cài đặt gói hỗ trợ Playwright. | Chạy lệnh `pip install -e ".[login]"` rồi chạy tiếp `playwright install chromium`. |
| **Không mở được trình duyệt trên Linux** | Thiếu các thư viện đồ họa hệ thống. | Chạy lệnh `playwright install-deps chromium`. |
| **Đồng bộ Google dừng sau 7 ngày** | Ứng dụng Google Cloud đang ở trạng thái "Testing". | Bấm tái ủy quyền trên Dashboard hoặc chuyển trạng thái OAuth sang "In Production". |
| **Lỗi giải mã trên máy chủ Docker** | Khóa `PHENIKAA_SERVER_KEY` bị thay đổi. | Khôi phục lại khóa Fernet ban đầu hoặc xóa thư mục dữ liệu để tạo lại. |

---

## 2. Sự Cố Về Phiên Đăng Nhập & Xác Thực

### Lỗi "Phenikaa session expired; log in again" (HTTP 401)
- **Nguyên nhân**: Token JWT của Phenikaa có thời hạn ngắn. Ngoài ra, cơ chế bảo mật của cổng trường sẽ hủy token cũ nếu bạn đăng nhập trên một trình duyệt hay thiết bị khác.
- **Cách khắc phục**:
  1. Mở trang web: `https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx#lichhoc`.
  2. Đăng nhập lại bằng tài khoản Microsoft trường cấp.
  3. Nếu dùng CLI: Chạy lại lệnh với cờ `--browser-login` để tự động cập nhật `.auth.json`.
  4. Nếu dùng giao diện Web: Nhấn nút **Kết nối lại (Reconnect)** cạnh tài khoản của bạn trên Dashboard.

### Lỗi không tìm thấy trang bootstrap trong cache trình duyệt
- **Nguyên nhân**: Trình duyệt Chrome đã tự động dọn dẹp các khối cache cũ trên đĩa, hoặc bạn quét nhầm profile Chrome khác với profile vừa đăng nhập.
- **Cách khắc phục**:
  1. Mở cổng trường trên Chrome và nhấn `F5` tải lại trang.
  2. Đảm bảo đường dẫn cache trỏ đúng profile (ví dụ: `Default` hoặc `Profile 1`).
  3. Hoặc bạn có thể dùng phím `Ctrl + S` lưu trang web thành file `index.aspx` và dùng cờ `--bootstrap-html` thay thế.

---

## 3. Sự Cố Về Dữ Liệu Thời Khóa Biểu

### Lỗi "The API returned no calendar events for the requested range"
- **Nguyên nhân**: Cổng trường không hỗ trợ truy vấn theo "Mã học kỳ" mà truy vấn trực tiếp theo ngày bắt đầu và kết thúc. Nếu bạn chọn khoảng ngày rơi vào dịp nghỉ hè hoặc lệch tuần học, API sẽ trả về danh sách rỗng.
- **Cách khắc phục**: Công cụ chủ động từ chối tạo file rỗng để tránh nhầm lẫn. Bạn chỉ cần mở rộng khoảng ngày cho bao trọn toàn bộ học kỳ:
  ```bash
  python phenikaa_exporter.py --start 2026-08-01 --end 2027-01-31 --auth-json .auth.json
  ```

### Lịch bị lệch giờ khi xem trên điện thoại
- **Nguyên nhân**: Việt Nam sử dụng cố định múi giờ **UTC+07:00** (`Asia/Ho_Chi_Minh`) và không áp dụng giờ mùa hè (DST). Nếu ứng dụng lịch của bạn bị ép về giờ UTC, giờ học sẽ bị lùi đi 7 tiếng.
- **Cách khắc phục**: Vào phần Cài đặt của ứng dụng lịch trên điện thoại, bật tùy chọn múi giờ và chọn múi giờ hiển thị là `Asia/Ho_Chi_Minh` hoặc `Hà Nội (GMT+7)`.

---

## 4. Sự Cố Khi Đồng Bộ Google Calendar

### Đồng bộ Google Calendar tự động dừng sau đúng 7 ngày
- **Nguyên nhân**: Khi tạo ứng dụng OAuth trên Google Cloud Console, nếu bạn để trạng thái phát hành (Publishing Status) là **Testing**, Google sẽ tự động thu hồi Refresh Token sau đúng 7 ngày.
- **Cách khắc phục**:
  - Truy cập [Google Cloud Console](https://console.cloud.google.com/apis/credentials/consent), bấm vào nút **Publish App** để chuyển trạng thái sang **In Production**. (Với ứng dụng dùng cá nhân hoặc nội bộ, bạn không cần phải thực hiện quy trình xác minh của Google; chỉ cần người dùng chấp nhận cảnh báo ứng dụng chưa xác minh khi đăng nhập lần đầu).
  - Trên Dashboard của máy chủ, nhấn nút **Ủy quyền lại Google Calendar (Authorize Google Calendar)** để nhận token mới.

### Bị trùng lặp lịch trên Google Calendar
- **Nguyên nhân**: Bạn vừa nhập thủ công file `.ics` vào lịch chính của Google, vừa bật tính năng tự động đồng bộ ngầm.
- **Cách khắc phục**: Lịch tự động đồng bộ sẽ luôn nằm trong bộ lịch riêng mang tên **`Phenikaa Learning Calendar`**. Bạn hãy vào bộ lịch chính cá nhân và xóa các sự kiện đã nhập tay trước đó.

---

## 5. Sự Cố Khi Vận Hành Máy Chủ Docker

### Lỗi "Chromium sandbox: Failed to launch" trong container Docker
- **Nguyên nhân**: Container Docker chạy dưới người dùng không có đặc quyền (unprivileged) nên cơ chế setuid sandbox của Linux bị chặn.
- **Cách khắc phục**: Bổ sung biến môi trường `-e PHENIKAA_BROWSER_NO_SANDBOX=true` khi khởi chạy container.

### Lỗi "database is locked" của SQLite
- **Nguyên nhân**: Bạn đang chạy nhiều bản sao (multiple replicas/instances) cùng trỏ vào một thư mục dữ liệu dùng chung.
- **Cách khắc phục**: Chạy **duy nhất 1 replica** của container. Cơ sở dữ liệu SQLite và hồ sơ Playwright được thiết kế cho kiến trúc máy chủ đơn cục bộ.

---

## 6. Hướng Dẫn Khi Cổng Thông Tin Trường Cập Nhật Mã Nguồn

Cổng đào tạo của Trường Đại học Phenikaa là hệ thống nội bộ. Nếu một đợt nâng cấp của nhà trường làm gián đoạn việc lấy lịch, các bạn lập trình viên hãy kiểm tra lần lượt các tệp mã nguồn sau trên trang web của trường:

1. `Config.js`: Đường dẫn gốc của các dịch vụ API.
2. `Core/systemroot.js`: Hàm `makeRequest` và các tham số khởi tạo yêu cầu.
3. `assets/js/crypto-js.js`: Các hàm biến đổi mã hóa `AE` và `AD`.
4. `modules/thoikhoabieu/script/lichgiang.js`: Tên action API, tên hàm và các trường dữ liệu thời khóa biểu.
