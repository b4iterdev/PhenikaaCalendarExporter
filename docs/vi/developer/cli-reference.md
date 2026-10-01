# Tham Chiếu Dòng Lệnh (CLI)

Giao diện dòng lệnh `phenikaa_exporter.py` cung cấp công cụ độc lập, có thể viết kịch bản tự động (scriptable) để lấy, giải mã và xuất thời khóa biểu mà không cần khởi chạy máy chủ web.

---

## 1. Cú Pháp Câu Lệnh

```bash
python phenikaa_exporter.py \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  <NGUỒN_XÁC_THỰC> \
  [TÙY_CHỌN_ĐẦU_RA]
```

Hoặc nếu đã cài đặt qua `pip install -e .`:

```bash
phenikaa-calendar-exporter \
  --start YYYY-MM-DD \
  --end YYYY-MM-DD \
  <NGUỒN_XÁC_THỰC> \
  [TÙY_CHỌN_ĐẦU_RA]
```

---

## 2. Danh Sách Tham Số Chi Tiết

### 2.1. Tham Số Khoảng Ngày (Bắt buộc)

| Cờ Lệnh | Định Dạng | Bắt Buộc | Mô Tả |
|---|---|---|---|
| `--start` | `YYYY-MM-DD` | **Có** | Ngày bắt đầu lấy lịch (bao gồm ngày này). |
| `--end` | `YYYY-MM-DD` | **Có** | Ngày kết thúc lấy lịch (bao gồm ngày này). Không được trước ngày `--start`. |

> **Mẹo**: Vì API cổng đào tạo không chấp nhận mã học kỳ mà yêu cầu khoảng ngày cụ thể, bạn nên cung cấp một khoảng thời gian rộng bao quát toàn bộ học kỳ (ví dụ: `--start 2026-08-01 --end 2027-01-31`).

---

### 2.2. Nguồn Xác Thực (Chọn Đúng Một Trong Bốn)

Bạn bắt buộc phải cung cấp chính xác 1 trong 4 cờ lệnh sau:

| Cờ Lệnh | Kiểu | Mô Tả |
|---|---|---|
| `--browser-login` | Cờ bật | Mở một cửa sổ Chromium do Playwright điều khiển, chờ bạn đăng nhập thủ công, tự động trích xuất thông tin vào file `.auth.json` (phân quyền 0600) và tiến hành xuất lịch. |
| `--auth-json ĐƯỜNG_DẪN` | Đường dẫn tệp | Đọc thông tin phiên từ một file JSON có cấu trúc `{"userId": "...", "tokenJWT": "..."}`. |
| `--bootstrap-html ĐƯỜNG_DẪN` | Đường dẫn tệp | Đọc và giải mã thông tin phiên từ file `index.aspx` (hoặc `index.html`) đã lưu từ cổng đào tạo. |
| `--cache-dir ĐƯỜNG_DẪN` | Thư mục | Tự động quét tìm phản hồi xác thực mới nhất trong thư mục bộ nhớ đệm (`Cache_Data`) của trình duyệt Chrome hoặc Chromium. |

---

### 2.3. Tùy Chọn Xuất File (Không bắt buộc)

| Cờ Lệnh | Mặc Định | Mô Tả |
|---|---|---|
| `--out-dir THƯ_MỤC` | `exports` | Thư mục chứa các file xuất ra. Sẽ tự động tạo nếu chưa có. |
| `--prefix TIỀN_TỐ` | `phenikaa_calendar` | Tiền tố tên file (ví dụ: `<prefix>.xlsx`, `<prefix>.ics`, `<prefix>.json`). |
| `--calendar-name TÊN_LỊCH` | `Phenikaa Learning Calendar` | Tên hiển thị của bộ lịch được ghi vào thẻ `X-WR-CALNAME` của file `.ics`. |

---

## 3. Định Dạng Dữ Liệu Đầu Ra (stdout)

Khi chạy thành công, công cụ sẽ in ra một đối tượng JSON chuẩn ở luồng `stdout`:

```json
{
  "events": 70,
  "classes": 65,
  "exams": 5,
  "date_start": "2026-08-04",
  "date_end": "2026-10-28",
  "json": "/Users/user/PhenikaaCalendarExporter/exports/phenikaa_calendar.json",
  "xlsx": "/Users/user/PhenikaaCalendarExporter/exports/phenikaa_calendar.xlsx",
  "ics": "/Users/user/PhenikaaCalendarExporter/exports/phenikaa_calendar.ics"
}
```

Các thông báo trạng thái, cảnh báo tiến trình hoặc thông báo lưu trữ token chỉ được in ra luồng `stderr`. Nhờ đó, bạn hoàn toàn có thể kết hợp lệnh này với công cụ `jq` trong các script shell tự động hóa.

---

## 4. Mã Trả Về & Bắt Lỗi (Exit Codes)

| Mã Thoát | Tình Huống | Nguyên Nhân & Cách Khắc Phục |
|---|---|---|
| `0` | Thành công | Tất cả các file đã được tạo và ghi ra đĩa thành công. |
| `1` / `2` | Sai cú pháp | Thiếu tham số bắt buộc hoặc truyền nhiều nguồn xác thực cùng lúc. |
| `RuntimeError` | Không có sự kiện | Cổng đào tạo trả về 0 sự kiện trong khoảng ngày đã chọn. Hãy mở rộng khoảng ngày `--start` và `--end`. |
| `PermissionError` | HTTP 401 | Phiên đăng nhập Phenikaa đã hết hạn hoặc bị đăng xuất từ thiết bị khác. Cần đăng nhập lại. |
| `ValueError` | Dữ liệu hỏng | File xác thực hoặc thư mục cache không chứa đúng thông tin `userId` và `tokenJWT`. |

---

## 5. Ví Dụ Chạy Thực Tế

### Ví dụ 1: Đăng nhập lần đầu bằng trình duyệt & xuất lịch
```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2027-01-31 \
  --browser-login \
  --out-dir ./lich_hoc \
  --prefix ky_1
```

### Ví dụ 2: Tự động chạy lại với file thông tin đã lưu
```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2027-01-31 \
  --auth-json .auth.json \
  --out-dir ./lich_hoc \
  --prefix ky_1
```

### Ví dụ 3: Trích xuất lịch trực tiếp từ bộ nhớ đệm Google Chrome trên Mac
```bash
python phenikaa_exporter.py \
  --start 2026-08-01 --end 2026-10-31 \
  --cache-dir "$HOME/Library/Caches/Google/Chrome/Default/Cache/Cache_Data" \
  --out-dir exports
```
