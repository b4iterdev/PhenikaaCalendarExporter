# Kiến Trúc Hệ Thống

Tài liệu này mô tả chi tiết thiết kế kiến trúc, các hệ thống con và luồng dữ liệu của dự án **Phenikaa Calendar Exporter**.

---

## 1. Sơ Đồ Kiến Trúc Tổng Thể

Hệ thống được thiết kế theo mô hình tách lớp linh hoạt, cho phép chạy độc lập dưới dạng công cụ dòng lệnh (CLI) hoặc triển khai dưới dạng dịch vụ web đa người dùng:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          Điểm Đầu Vào (Entry Points)                   │
│                                                                        │
│    [ Công Cụ CLI: phenikaa_exporter.py ]     [ Máy Chủ Web: server/ ]  │
└───────────────────┬──────────────────────────────────┬─────────────────┘
                    │                                  │
                    ▼                                  ▼
┌──────────────────────────────────────┐   ┌─────────────────────────────┐
│          Dịch Vụ Miền Cốt Lõi        │   │       Hệ Thống Con Máy Chủ  │
│                                      │   │                             │
│ • Mã hóa/Giải mã XOR (AE/AD)         │   │ • Xác thực OIDC / Google SSO│
│ • Client gọi API Thời khóa biểu      │   │ • SQLite & Mã hóa TokenVault│
│ • Chuẩn hóa & Khử trùng lặp sự kiện  │   │ • Tiến trình ngầm SyncEngine│
│ • Bộ xuất file (XLSX, ICS, JSON)     │   │ • Điều phối Playwright      │
│ • Bắt token qua Playwright           │   │ • Đồng bộ Google Calendar   │
└───────────────────┬──────────────────┘   └──────────────┬──────────────┘
                    │                                     │
                    ▼                                     ▼
        ┌───────────────────────┐             ┌───────────────────────┐
        │  Cổng Đào Tạo Phenikaa│             │  Google Calendar API  │
        │ (qldtbeta.phenikaa...)│             │ (Lịch do app tạo)     │
        └───────────────────────┘             └───────────────────────┘
```

---

## 2. Phân Tích Các Thành Phần Cốt Lõi

### 2.1. Module Độc Lập (`phenikaa_exporter.py`)
Được thiết kế độc lập, không phụ thuộc vào bất kỳ framework web nặng nào ngoài thư viện `openpyxl` (cho file Excel) và thư viện chuẩn của Python:
- **`xor_b64_encode` / `xor_b64_decode`**: Tái hiện thuật toán xáo trộn ký tự phía frontend của cổng trường (`AE` và `AD`).
- **`parse_bootstrap_html` & `extract_auth_from_cache`**: Trích xuất khối dữ liệu `AXYZCLRVN` từ HTML hoặc tự động quét bộ nhớ đệm (disk cache) của trình duyệt Chromium.
- **`fetch_calendar`**: Đóng gói payload được mã hóa XOR, gửi yêu cầu HTTP POST kèm Bearer token và giải mã phong bì dữ liệu JSON phản hồi.
- **`normalize_events`**: Làm sạch các thẻ HTML `<br>`, loại bỏ khoảng trắng thừa, khử trùng lặp các tiết học bị lặp lại bằng bộ nhận diện 6 trường `(ID, NGAYHOC, GIOBATDAU, PHUTBATDAU, TENHOCPHAN, TENLOPHOCPHAN)`, và sắp xếp theo trình tự thời gian.
- **`write_xlsx`**: Tạo tệp Excel có định dạng chuyên nghiệp, cố định dòng tiêu đề, tô màu cảnh báo buổi thi và tạo bảng thống kê tổng hợp số tiết từng môn.
- **`write_ics`**: Tạo tệp lịch chuẩn RFC 5545 với múi giờ cố định `Asia/Ho_Chi_Minh` và kỹ thuật ngắt dòng UTF-8 chuẩn 75 octet.

### 2.2. Hỗ Trợ Đăng Nhập Tự Động (`phenikaa_login.py`)
- Sử dụng Playwright mở trình duyệt Chromium trực quan đến cổng đào tạo.
- Thiết lập trình lắng nghe sự kiện mạng (network sniffer) để chặn bắt khối `AXYZCLRVN` trong phản hồi và Header `Authorization: Bearer <tokenJWT>` trong yêu cầu.
- Ghi phiên đăng nhập ra file `.auth.json` với quyền hạn tệp an toàn tuyệt đối `0600` (chỉ chủ sở hữu được đọc/ghi).

### 2.3. Máy Chủ Web Đa Người Dùng (`server/`)
- **`server/config.py`**: Quản lý cấu hình đọc từ biến môi trường (`PHENIKAA_SERVER_*`), đường dẫn tệp và tính toán khung thời gian học kỳ.
- **`server/crypto.py`**: Sử dụng thuật toán AES-128-CBC với Fernet (`TokenVault`) để mã hóa toàn bộ Bearer token và Google Refresh token trong cơ sở dữ liệu SQLite. Tính toán mã băm SHA-256 fingerprint cho token.
- **`server/db.py`**: Quản lý cơ sở dữ liệu SQLite, ràng buộc khóa ngoại (foreign key) và hành vi xóa phân tầng (cascade delete).
- **`server/login_broker.py`**: Quản lý các phiên đăng nhập Playwright từ xa và truyền phát luồng sự kiện (SSE) về giao diện web.
- **`server/sync.py`**: Luồng tiến trình ngầm (`SyncEngine`) định kỳ làm mới token hết hạn và thực hiện đồng bộ một chiều sang Google Calendar.
- **`server/google.py` & `server/google_login.py`**: Quản lý vòng đời token OAuth của Google, tạo lịch học riêng `Phenikaa Learning Calendar`, tính toán độ lệch (diffing: thêm, sửa, xóa sự kiện).
- **`server/oidc.py`**: Tích hợp xác thực OpenID Connect với cơ chế khám phá khóa JWKS RS256 và xác thực chữ ký token.
- **`server/web.py`**: Máy chủ HTTP xử lý xuất lịch công khai (one-shot export), hiển thị giao diện song ngữ và quản lý cookie phiên.

---

## 3. Luồng Dữ Liệu & Mô Hình Bảo Mật

### 3.1. Luồng Xuất Nhanh Một Lần (One-Shot Public Export)
```
Trình Duyệt Người Dùng             Tiến Trình Máy Chủ Web             API Cổng Trường
         │                                      │                            │
         ├─── 1. POST HTML hoặc mã token ──────►│                            │
         │    (Giới hạn tối đa 1MB)             ├── 2. Trích xuất thông tin  │
         │                                      ├── 3. Gọi lấy lịch ────────►│
         │                                      │◄── 4. Nhận JSON mã hóa ────┘
         │                                      ├── 5. Giải mã trong RAM     │
         │                                      ├── 6. Tạo file ZIP ở /tmp   │
         │◄── 7. Trả file ZIP (no-store) ───────┤                            │
         │                                      └── 8. Xóa sạch RAM & /tmp   │
```
*Tại không có thời điểm nào thông tin xác thực hay file lịch xuất nhanh bị ghi vào cơ sở dữ liệu lâu dài.*

### 3.2. Luồng Đồng Bộ Nền Tự Động (Background Sync)
1. **SyncEngine** thức dậy định kỳ theo `sync_interval_hours` (mặc định 24 giờ).
2. Duyệt qua từng phiên đăng nhập đang kích hoạt trong SQLite:
   - Khóa thư mục hồ sơ trình duyệt để tránh xung đột ghi đĩa.
   - Nếu token JWT đã hết hạn, khởi chạy Chromium không giao diện (headless) để cổng trường cấp lại token mới từ cookie đã lưu.
   - Gọi `fetch_calendar()` lấy lịch toàn bộ năm học.
   - Cập nhật các file tĩnh xuất ra trên đĩa (`exports/<session_id>.ics`).
   - Nếu người dùng có liên kết Google Calendar:
     - Kiểm tra hoặc tạo lịch `Phenikaa Learning Calendar`.
     - Lấy danh sách các sự kiện hiện có trên Google Calendar.
     - So khớp danh sách sự kiện (Diffing): thêm buổi mới, cập nhật buổi đổi phòng/giờ, xóa buổi đã bị hủy trên trường.
     - Ghi nhật ký đồng bộ và thời gian vào SQLite.
