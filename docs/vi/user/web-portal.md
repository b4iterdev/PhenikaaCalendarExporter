# Hướng Dẫn Cổng Web & Bảng Điều Khiển

Giao diện web giúp bạn trích xuất lịch học và quản lý đồng bộ một cách trực quan, dễ dàng mà không cần gõ bất kỳ dòng lệnh nào.

---

## 1. Xuất Nhanh Một Lần (Không Cần Đăng Nhập)

Nếu bạn chỉ muốn tải file Excel hoặc file lịch `.ics` để xem một lần mà không muốn đăng ký tài khoản hay lưu thông tin trên máy chủ:

1. Truy cập vào trang chủ của máy chủ (ví dụ: `https://calendar.example.edu`).
2. Chọn tab **Xuất lịch công khai** (Public export).
3. Chọn khoảng ngày bạn muốn lấy lịch (thường là từ đầu kỳ học đến hết đợt thi, ví dụ: `01/08/2026` đến `31/01/2027`).
4. Cung cấp thông tin phiên đăng nhập bằng một trong hai cách dưới đây:

### Cách A: Dùng file `index.aspx` đã lưu từ trình duyệt (Dễ nhất)
1. Dùng trình duyệt Chrome, Edge hoặc Cốc Cốc trên máy tính, đăng nhập vào cổng sinh viên: `https://qldtbeta.phenikaa-uni.edu.vn`.
2. Mở mục **Thời khóa biểu** (hoặc truy cập `#lichhoc`).
3. Nhấn tổ hợp phím **Ctrl + S** (Windows) hoặc **Cmd + S** (Mac). Chọn định dạng **"Trang web, chỉ HTML"** (Webpage, HTML Only) và lưu file `index.aspx`.
4. Quay lại trang xuất lịch công khai, chọn mục **"Dùng mã HTML đã đăng nhập"** và tải file vừa lưu lên (hoặc mở file dán toàn bộ nội dung vào khung).
5. Nhấn nút **Tải xuống lịch học**.

> **💡 Cơ chế bảo mật**: File `index.aspx` chứa một đoạn mã xác thực tạm thời (`AXYZCLRVN`). Máy chủ chỉ đọc đoạn mã này trong bộ nhớ RAM để gửi yêu cầu lấy lịch về, nén thành file `.zip` cho bạn tải xuống và xóa bỏ ngay lập tức. Hệ thống tuyệt đối không lưu trữ bất kỳ thông tin nào vào cơ sở dữ liệu.

### Cách B: Nhập trực tiếp User ID và Mã Token JWT
1. Tại trang thời khóa biểu đã đăng nhập, nhấn phím **F12** trên bàn phím để mở Developer Tools → chuyển sang tab **Console**.
2. Gõ dòng lệnh: `window.edu?.system?.userId` rồi nhấn Enter để lấy mã sinh viên nội bộ (chuỗi 32 ký tự).
3. Chuyển sang tab **Network**, nhấp vào một yêu cầu API bất kỳ, tìm mục Header `Authorization: Bearer <token>` và sao chép phần chuỗi mã JWT (bỏ chữ `Bearer ` đi).
4. Dán hai giá trị này vào ô tương ứng trên trang web rồi nhấn **Tải xuống lịch học**.

Trình duyệt của bạn sẽ tự động tải về file `phenikaa-calendar-export.zip` chứa đầy đủ 3 file: `calendar.xlsx`, `calendar.ics` và `calendar.json`.

---

## 2. Sử Dụng Bảng Điều Khiển (Khi Đã Có Tài Khoản)

Đăng nhập tài khoản giúp máy chủ có thể tự động giữ lịch của bạn luôn mới và đồng bộ tự động sang Google Calendar.

### Đăng Nhập
1. Nhấn nút **Đăng nhập** ở góc trên bên phải màn hình.
2. Đăng nhập bằng tài khoản Google hoặc tài khoản trường (tùy cấu hình hệ thống).
3. Sau khi xác thực thành công, bạn sẽ được đưa đến **Bảng điều khiển cá nhân (Dashboard)**.

### Kết Nối Tài Khoản Sinh Viên Phenikaa
Để hệ thống có thể lấy lịch, bạn chỉ cần liên kết một lần:
1. Tại Dashboard, nhấn vào nút **Kết nối tài khoản Phenikaa**.
2. Một cửa sổ đăng nhập sẽ hiển thị trang đăng nhập Microsoft chính thức của Trường Đại học Phenikaa.
3. Bạn điền tài khoản sinh viên (`...@st.phenikaa-uni.edu.vn`), mật khẩu và xác thực OTP Microsoft Authenticator như bình thường.
4. Ngay khi đăng nhập xong, hệ thống sẽ tự động nhận diện phiên, đóng cửa sổ lại và chuyển trạng thái sang **Đã kết nối (Active)**.

> **Lưu ý quan trọng**: Quá trình đăng nhập diễn ra trên nền tảng Microsoft chính thống của trường. Máy chủ chỉ nhận token phiên đăng nhập (giống như trình duyệt lưu cookie), hoàn toàn không ghi nhận hoặc lưu mật khẩu của bạn.

---

## 3. Các Chức Năng Trên Bảng Điều Khiển

Khi đã kết nối thành công, màn hình Dashboard cung cấp cho bạn:

- 📊 **Tổng quan kỳ học**: Thống kê tổng số môn học, số buổi học trên lớp và số buổi thi kết thúc học phần.
- 🔄 **Trạng thái đồng bộ**: Hiển thị thời gian lần đồng bộ gần nhất và trạng thái hiện tại.
- 💾 **Tải trọn bộ file**: Bấm nút tải về để nhận các file `.ics`, `.xlsx` mới nhất bất cứ lúc nào.
- ⚡ **Đồng bộ thủ công (Sync Now)**: Nếu bạn vừa đổi lớp học phần hoặc phòng học trên trường vừa đổi, bấm nút này để hệ thống cập nhật lịch mới ngay tức thì.
- ⏸️ **Tạm dừng / Tiếp tục đồng bộ**: Cho phép bạn tạm dừng cập nhật tự động khi đang nghỉ hè hoặc nghỉ Tết.
- 🗑️ **Ngắt kết nối & Xóa dữ liệu**: Xóa hoàn toàn phiên đăng nhập khỏi máy chủ chỉ với một cú nhấp chuột.

---

## 4. Tùy Chọn Ngôn Ngữ

Hệ thống hỗ trợ song ngữ hoàn chỉnh:
- Bấm vào nút chuyển đổi ngôn ngữ ở thanh menu phía trên để đổi qua lại giữa **Tiếng Việt** và **English**.
- Lựa chọn của bạn sẽ được tự động lưu lại cho các lần truy cập tiếp theo.
