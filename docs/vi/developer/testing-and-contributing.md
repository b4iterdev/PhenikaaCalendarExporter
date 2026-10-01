# Hướng Dẫn Kiểm Thử & Đóng Góp Mã Nguồn

Tài liệu này hướng dẫn cách chạy bộ kiểm thử tự động (unit test), thẩm định các thay đổi mã nguồn và quy chuẩn đóng góp cho dự án **Phenikaa Calendar Exporter**.

---

## 1. Chạy Bộ Kiểm Thử Tự Động

Toàn bộ các bài kiểm thử đều sử dụng framework chuẩn `unittest` của Python và không đòi hỏi cài đặt thêm công cụ kiểm thử bên ngoài:

```bash
# Chạy toàn bộ các bài kiểm thử trong thư mục tests
python -m unittest discover -s tests -v
```

Để chạy kiểm tra một module cụ thể:

```bash
# Kiểm thử module xuất lịch cốt lõi và thuật toán mã hóa
python -m unittest tests/test_exporter.py -v

# Kiểm thử cơ sở dữ liệu và mã hóa token
python -m unittest tests/test_server_storage.py -v

# Kiểm thử luồng đồng bộ Google Calendar
python -m unittest tests/test_server_google.py -v

# Kiểm thử các endpoint web và bảo vệ CSRF
python -m unittest tests/test_server_web.py -v
```

---

## 2. Kiến Trúc Bộ Kiểm Thử

| Tệp Kiểm Thử | Nội Dung Xác Minh |
|---|---|
| `test_exporter.py` | Kiểm tra thuật toán mã hóa/giải mã XOR, trích xuất token từ HTML và bộ nhớ đệm Chromium, kiểm tra logic khoảng ngày, khử trùng lặp bản ghi, định dạng file Excel, ngắt dòng chuẩn RFC 5545 cho file ICS và xử lý tham số CLI. |
| `test_server_storage.py` | Kiểm tra cấu trúc bảng SQLite, ràng buộc khóa ngoại, hành vi xóa phân tầng (cascade delete) và tính toàn vẹn của mã hóa/giải mã Fernet trong `TokenVault`. |
| `test_server_web.py` | Kiểm tra định tuyến máy chủ web, ký chữ ký số cookie phiên, chống tấn công CSRF, luồng xuất nhanh một lần và cookie chuyển đổi ngôn ngữ giao diện. |
| `test_server_sync.py` | Kiểm tra bộ lập lịch tiến trình ngầm `SyncEngine`, chu kỳ đồng bộ, xử lý ngoại lệ mạng và cơ chế khóa an toàn thư mục hồ sơ. |
| `test_server_google.py` | Kiểm tra quá trình trao đổi mã code OAuth, làm mới access token, tạo và bảo trì lịch `Phenikaa Learning Calendar` và giải thuật so khớp sự kiện (thêm, cập nhật, xóa). |
| `test_server_google_login.py`| Kiểm tra chế độ kết hợp đăng nhập Google và quyền Calendar, tái ủy quyền khi hết hạn và lưu trữ token offline an toàn. |
| `test_server_oidc.py` | Kiểm tra luồng OIDC tiêu chuẩn, phân giải khóa JWKS RS256 giả lập, xác minh JWT và cookie trạng thái giao dịch. |
| `test_server_browser.py` | Kiểm tra cơ chế khóa đồng thời cho hồ sơ trình duyệt và luồng truyền phát sự kiện đăng nhập Playwright. |
| `test_server_packaging.py` | Kiểm tra định nghĩa setuptools console scripts và metadata đóng gói wheel. |

---

## 3. Quy Chuẩn Đóng Góp Mã Nguồn

### 3.1. Triết Lý Thiết Kế
1. **Hạn Chế Phụ Thuộc (Minimal Dependencies)**: Giữ cho công cụ dòng lệnh `phenikaa_exporter.py` gọn nhẹ tối đa. Tuyệt đối không đưa thêm các thư viện cồng kềnh vào phần cốt lõi nếu không thật sự cần thiết.
2. **Ưu Tiên Bảo Mật & Quyền Riêng Tư**: Mọi thông tin nhạy cảm (Bearer token, Refresh token, cookie) không bao giờ được phép in ra `stdout`, ghi dưới dạng văn bản rõ trong database hay xuất hiện trong stack trace lỗi.
3. **Viết Kiểm Thử Tái Hiện Lỗi Trước (Test-First)**: Khi sửa lỗi do cổng đào tạo thay đổi API hay cấu trúc dữ liệu, hãy viết một bài kiểm thử tái hiện lỗi thất bại trước, sau đó mới tiến hành sửa mã nguồn.

### 3.2. Tiêu Chuẩn Lập Trình
- Mục tiêu hỗ trợ từ **Python 3.9+**.
- Luôn khai báo `from __future__ import annotations` ở đầu mỗi tệp.
- Sử dụng đầy đủ gợi ý kiểu dữ liệu (type hinting) cho mọi định nghĩa hàm.
- Không sử dụng import đại diện dạng sao chép tự do (`from module import *`).
- Các bài test phải tự cô lập bằng `tempfile.TemporaryDirectory` và `unittest.mock`.

### 3.3. Quy Trình Gửi Pull Request
1. Tạo một nhánh tính năng mới: `git checkout -b feature/tinh-nang-moi`.
2. Viết mã nguồn kèm bài kiểm thử tương ứng.
3. Chạy toàn bộ kiểm thử để đảm bảo pass 100%: `python -m unittest discover -s tests -v`.
4. Mở Pull Request mô tả chi tiết mục đích thay đổi và kết quả kiểm thử thực tế.
