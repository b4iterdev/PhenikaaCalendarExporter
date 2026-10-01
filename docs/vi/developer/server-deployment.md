# Hướng Dẫn Triển Khai Máy Chủ & Docker

Máy chủ đồng bộ thời khóa biểu (`phenikaa-calendar-server`) chịu trách nhiệm định kỳ quét thời khóa biểu từ cổng trường, tự động làm mới token và đồng bộ sự kiện vào Google Calendar của người dùng.

---

## 1. Triển Khai Nhanh Với Docker (Khuyên Dùng)

Hình ảnh Docker hỗ trợ đa kiến trúc CPU (`linux/amd64` và `linux/arm64`) đã được biên dịch sẵn trên GitHub Container Registry:

```bash
# 1. Tạo khóa mã hóa bảo mật Fernet
KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 2. Khởi chạy container Docker
docker run -d \
  --name phenikaa-calendar \
  --restart unless-stopped \
  -p 8416:8416 \
  -v phenikaa-data:/data \
  -e PHENIKAA_SERVER_KEY="$KEY" \
  -e PHENIKAA_SERVER_BASE_URL="https://calendar.example.edu" \
  -e PHENIKAA_POLICY_CONTACT="admin@example.edu" \
  -e PHENIKAA_SERVER_AUTH="google" \
  -e PHENIKAA_GOOGLE_CLIENT_ID="YOUR_CLIENT_ID.apps.googleusercontent.com" \
  -e PHENIKAA_GOOGLE_CLIENT_SECRET="YOUR_CLIENT_SECRET" \
  -e PHENIKAA_GOOGLE_REDIRECT_URI="https://calendar.example.edu/auth/google/callback" \
  ghcr.io/b4iterdev/phenikaa-calendar-exporter:latest
```

---

## 2. Bảng Biến Môi Trường Cấu Hình

| Biến Môi Trường | Bắt Buộc | Mặc Định | Mô Tả |
|---|---|---|---|
| `PHENIKAA_SERVER_KEY` | **Có** | *Không có* | Khóa Fernet 32-byte dùng để mã hóa an toàn các token sinh viên và refresh token trong SQLite. |
| `PHENIKAA_SERVER_BASE_URL` | **Có** | `http://127.0.0.1:8416` | Địa chỉ tên miền chính thức của dịch vụ (ví dụ: `https://calendar.example.edu`). |
| `PHENIKAA_POLICY_CONTACT` | Không | `the server operator` | Thông tin liên hệ của quản trị viên hiển thị trên trang Điều khoản và Chính sách bảo mật. |
| `PHENIKAA_SERVER_AUTH` | Không | `oidc` | Phương thức đăng nhập ứng dụng: `google`, `oidc`, hoặc `disabled` (dành cho lập trình viên thử nghiệm cục bộ). |
| `PHENIKAA_SERVER_HOST` | Không | `127.0.0.1` | Địa chỉ IP máy chủ lắng nghe. |
| `PHENIKAA_SERVER_PORT` | Không | `8416` | Cổng mạng TCP ứng dụng lắng nghe. |
| `PHENIKAA_SERVER_STATE` | Không | `server-state` | Thư mục lưu trữ database, exports và hồ sơ trình duyệt. Đặt là `/data` trong Docker. |
| `PHENIKAA_SERVER_SYNC_INTERVAL_HOURS`| Không | `24` | Số giờ giữa các chu kỳ tự động quét và đồng bộ lịch học ngầm. |
| `PHENIKAA_BROWSER_NO_SANDBOX` | Không | `false` | Thêm cờ `--no-sandbox` cho Chromium khi chạy trong môi trường container không có quyền root. |

---

## 3. Các Chế Độ Xác Thực

### Chế Độ 1: Tích Hợp Đăng Nhập Google (`PHENIKAA_SERVER_AUTH=google`)
Ở chế độ này, người dùng bấm nút **Sign in with Google**. Cùng một tài khoản Google đó vừa dùng để đăng nhập hệ thống, vừa là đích nhận lịch cho bộ lịch **Phenikaa Learning Calendar**.

#### Các bước thiết lập trên Google Cloud:
1. Truy cập Google Cloud Console, kích hoạt **Google Calendar API**.
2. Cấu hình Màn hình chấp thuận OAuth (OAuth Consent Screen). Nếu ứng dụng ở trạng thái Testing, cần thêm email người dùng vào danh sách Test Users.
3. Tạo thông tin xác thực OAuth dạng **Web application** (Ứng dụng web).
4. Đăng ký Authorized Redirect URI là:
   `${PHENIKAA_SERVER_BASE_URL}/auth/google/callback`
5. Khai báo các biến môi trường:
   - `PHENIKAA_GOOGLE_CLIENT_ID`
   - `PHENIKAA_GOOGLE_CLIENT_SECRET`
   - `PHENIKAA_GOOGLE_REDIRECT_URI`

### Chế Độ 2: Xác Thực Đăng Nhập Doanh Nghiệp / OIDC (`PHENIKAA_SERVER_AUTH=oidc`)
Phù hợp khi trường đã có sẵn hệ thống đăng nhập tập trung SSO (như Keycloak, Authentik, Azure AD / Microsoft Entra ID).
- Cần cung cấp:
  - `PHENIKAA_OIDC_ISSUER`: Đường dẫn khám phá metadata OIDC.
  - `PHENIKAA_OIDC_CLIENT_ID`: Mã Client ID.
  - `PHENIKAA_OIDC_CLIENT_SECRET`: Mã bí mật Client Secret.
  - `PHENIKAA_OIDC_REDIRECT_URI`: `${PHENIKAA_SERVER_BASE_URL}/auth/callback`.

---

## 4. Cấu Trúc Lưu Trữ Dữ Liệu (`/data`)

Hệ thống lưu trữ toàn bộ trạng thái bên trong thư mục `/data`:

```text
/data/
├── server.db        # Cơ sở dữ liệu SQLite chứa người dùng, phiên và liên kết sự kiện
├── cookie.secret    # Khóa bí mật dùng để ký chữ ký số HMAC cho session cookie
├── secret.key       # Khóa dự phòng
├── profiles/        # Thư mục lưu trữ cookie hồ sơ Playwright của từng phiên
│   └── <session_id>/
└── exports/         # Bộ đệm tệp lịch tĩnh .ics, .xlsx, .json
    └── <session_id>/
```

> **⚠️ Lưu ý vận hành**: Chỉ chạy **duy nhất 1 replica** (một instance) của container. Cơ sở dữ liệu SQLite, tiến trình Playwright và cơ chế khóa tệp không thể chia sẻ qua nhiều máy chủ cùng lúc nếu không có cơ chế điều phối chuyên biệt.

---

## 5. Cấu Hình Reverse Proxy Mẫu Với Nginx

Cookie phiên của ứng dụng luôn được bật cờ `Secure` khi chạy qua HTTPS. Dưới đây là tệp cấu hình mẫu cho Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name calendar.example.edu;

    ssl_certificate /etc/letsencrypt/live/calendar.example.edu/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/calendar.example.edu/privkey.pem;

    client_max_body_size 2M;

    location / {
        proxy_pass http://127.0.0.1:8416;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Cấu hình giữ kết nối cho luồng truyền phát đăng nhập Playwright
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 600s;
    }

    # Bảo mật: Không ghi log chứa thông tin nhạy cảm của OAuth callback
    location ~* ^/auth/(callback|google/callback) {
        proxy_pass http://127.0.0.1:8416;
        access_log off;
    }
}
```
