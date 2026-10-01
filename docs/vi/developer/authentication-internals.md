# Cơ Chế Xác Thực & Phân Tích Nội Bộ

Tài liệu này giải thích chi tiết cơ chế xác thực của Cổng thông tin sinh viên Trường Đại học Phenikaa (`qldtbeta.phenikaa-uni.edu.vn`), thuật toán giải mã token phiên và cách dự án thu thập thông tin xác thực mà không bao giờ lưu trữ mật khẩu.

---

## 1. Cơ Chế Khởi Tạo Phiên (Bootstrap) Của Cổng Trường

Khi sinh viên hoặc giảng viên đăng nhập thành công qua Microsoft Entra ID (Azure AD), máy chủ cổng thông tin sẽ trả về trang HTML chính tại địa chỉ `/congsinhvien/index.aspx`.

Trong mã nguồn HTML của trang này có chứa một thẻ `<script>` khai báo một hàm ẩn danh với dữ liệu đã được làm rối (obfuscated):

```html
<script>
  AXYZCLRVN = () => "CHUOI_MA_HOA_BASE64";
</script>
```

### Thuật Toán Giải Mã (De-obfuscation)
Hàm tiện ích `AD(ciphertext, "AzzS")` trên trang web thực hiện 3 bước giải mã tuần tự:

```
┌──────────────────────────────────────┐
│ Chuỗi Dữ Liệu Mã Hóa Dạng Base64     │
└──────────────────┬───────────────────┘
                   │ 1. Giải mã Base64 sang chuỗi UTF-8
                   ▼
┌──────────────────────────────────────┐
│ Chuỗi Ký Tự Đã Bị Xáo Trộn Ký Tự     │
└──────────────────┬───────────────────┘
                   │ 2. Phép biến đổi XOR từng ký tự với khóa lặp "AzzS"
                   ▼
┌──────────────────────────────────────┐
│ Chuỗi Văn Bản JSON Nguyên Bản        │
└──────────────────┬───────────────────┘
                   │ 3. json.loads()
                   ▼
┌──────────────────────────────────────┐
│ { "userId": "...", "tokenJWT": "..." }│
└──────────────────────────────────────┘
```

Trong Python, thuật toán này được triển khai chuẩn xác như sau:

```python
def xor_b64_decode(encoded: str, key: str) -> str:
    encrypted = base64.b64decode(encoded).decode("utf-8")
    return "".join(chr(ord(char) ^ ord(key[index % len(key)])) for index, char in enumerate(encrypted))
```

Dữ liệu JSON thu được chứa hai thông tin quan trọng nhất:
- `userId`: Chuỗi mã định danh người học gồm 32 ký tự hexa.
- `tokenJWT`: Chuỗi JSON Web Token ngắn hạn, được gửi kèm trong tiêu đề `Authorization: Bearer <tokenJWT>` cho mọi yêu cầu lấy lịch.

---

## 2. Bắt Token Tự Động Qua Playwright (`phenikaa_login.py`)

Nhằm giúp người dùng không phải tự mở Developer Tools để tìm token, module `phenikaa_login.py` triển khai một cơ chế giám sát lưu lượng mạng thụ động bằng Playwright:

1. **Hồ Sơ Trình Duyệt Bền Vững (Persistent Profile)**: Chromium được khởi chạy kèm theo thư mục dữ liệu cá nhân (`.browser-profile/`). Điều này giúp lưu lại cookie đăng nhập của Microsoft cho các lần chạy sau.
2. **Thu Thập Qua 3 Kênh Đồng Thời**:
   - **Chặn bắt phản hồi (Response Sniffing)**: Kiểm tra nội dung mọi phản hồi HTML trả về. Nếu phát hiện có chứa từ khóa `AXYZCLRVN`, module sẽ gọi hàm `parse_bootstrap_html()` để giải mã ngay.
   - **Chặn bắt tiêu đề yêu cầu (Request Header Sniffing)**: Theo dõi các yêu cầu gửi tới endpoint `/sinhvienapi3/`. Ngay khi xuất hiện header `Authorization: Bearer ...`, chuỗi JWT sẽ được tách và lưu lại.
   - **Thực thi mã DOM**: Chạy ngầm biểu thức `window.edu?.system?.userId` ngay trong ngữ cảnh trang để dự phòng.
3. **Lưu Trữ Tệp Với Quyền Hạn An Toàn**:
   Sau khi thu thập đủ `userId` và `tokenJWT`, thông tin phiên được ghi ra file `.auth.json` với cờ phân quyền hệ thống `0600` (chỉ duy nhất người dùng hiện tại có quyền đọc và ghi):
   ```python
   handle = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
   with os.fdopen(handle, "w", encoding="utf-8") as stream:
       stream.write(payload + "\n")
   ```

---

## 3. Trích Xuất Dữ Liệu Từ Bộ Nhớ Đệm Trình Duyệt (`extract_auth_from_cache`)

Đối với các môi trường máy chủ Linux không có màn hình hoặc không thể cài đặt Playwright, công cụ CLI có thể trực tiếp quét bộ nhớ đệm (disk cache) của Google Chrome:

1. Chromium lưu cache dạng khối nhị phân dưới thư mục `Cache_Data`.
2. Trình quét sẽ duyệt qua các tệp cache mới nhất theo thời gian sửa đổi (`mtime`).
3. Các luồng phản hồi nén gzip bên trong tệp cache luôn bắt đầu bằng chuỗi byte ma thuật `\x1f\x8b\x08`.
4. Trình quét giải nén luồng này bằng `zlib.decompressobj(16 + zlib.MAX_WBITS)`.
5. Ngay khi tìm thấy chuỗi `AXYZCLRVN`, dữ liệu được phân tích và trích xuất mà không ghi bất kỳ thông tin nhạy cảm nào ra màn hình.

---

## 4. Quản Lý Vòng Đời Token Phía Máy Chủ (`TokenVault`)

Trong chế độ máy chủ web (`server/`):
- Toàn bộ token người dùng tuyệt đối **không** lưu dạng văn bản rõ trong SQLite.
- Module `server/crypto.py` sử dụng chuẩn mã hóa **Fernet (AES-128-CBC với xác thực HMAC-SHA256)** dựa trên khóa bí mật `PHENIKAA_SERVER_KEY`.
- Mã băm SHA-256 fingerprint được lưu trữ để phục vụ kiểm tra trạng thái mà không cần giải mã token.
- Khi token hết hạn (thường sau 24-48 giờ), tiến trình ngầm `SyncEngine` sẽ tự động khởi động một phiên Chromium không giao diện (headless) để truy cập lại cổng trường và nhận token mới dựa trên cookie đã lưu.
