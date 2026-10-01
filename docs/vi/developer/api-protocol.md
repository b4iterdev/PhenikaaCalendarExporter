# Đặc Tả Giao Thức API Nội Bộ Phenikaa

Tài liệu này ghi lại thông số kỹ thuật chi tiết của giao thức mạng nội bộ được Cổng thông tin sinh viên Trường Đại học Phenikaa (`qldtbeta.phenikaa-uni.edu.vn`) sử dụng để truy xuất thời khóa biểu cá nhân.

> **Tuyên bố miễn trừ trách nhiệm**: Đây là API nội bộ chưa được công bố chính thức của nhà trường. Các endpoint, khóa mã hóa và tên hàm trong tài liệu này được thu thập qua kỹ thuật dịch ngược (reverse engineering) từ các tệp JavaScript trên trình duyệt (`Core/systemroot.js`, `modules/thoikhoabieu/script/lichgiang.js`) vào ngày 26 tháng 8 năm 2026 và có thể thay đổi khi nhà trường nâng cấp hệ thống.

---

## 1. Endpoint Truy Vấn Lịch Học

```http
POST /sinhvienapi3/api/SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv HTTP/1.1
Host: qldtbeta.phenikaa-uni.edu.vn
Authorization: Bearer <tokenJWT>
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
Accept: application/json
Origin: https://qldtbeta.phenikaa-uni.edu.vn
Referer: https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx
```

---

## 2. Quy Chuẩn Đóng Gói & Mã Hóa Dữ Liệu Gửi Đi

Máy chủ không tiếp nhận định dạng JSON thuần. Thay vào đó, phía frontend của cổng trường áp dụng hàm làm rối dữ liệu `AE` trước khi gửi dưới dạng dữ liệu biểu mẫu tiêu chuẩn (`application/x-www-form-urlencoded`).

### 2.1. Cấu Trúc Payload JSON Gốc

```json
{
  "action": "SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv",
  "func": "pkg_congthongtin_hssv_thongtin.LayDSLichCaNhan",
  "iM": "AzzSystem",
  "strQLSV_NguoiHoc_Id": "<MA_SINH_VIEN_32_KY_TU>",
  "strNgayBatDau": "01/08/2026",
  "strNgayKetThuc": "31/01/2027",
  "strChucNang_Id": "",
  "strNguoiThucHien_Id": "<MA_SINH_VIEN_32_KY_TU>"
}
```

*Lưu ý: Định dạng ngày tháng bắt buộc phải là `DD/MM/YYYY`.*

### 2.2. Thuật Toán Làm Rối Dữ Liệu (`AE`)

1. Tách khóa mã hóa từ hậu tố của trường `action`:
   ```python
   CALENDAR_ACTION = "SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv"
   KEY = CALENDAR_ACTION.split("/", 1)[1]  # "DSA4BRINKCIpAiAPKSAv"
   ```
2. Chuyển đổi JSON thành chuỗi tối giản không có khoảng trắng thừa (`separators=(',', ':')`).
3. Thực hiện phép toán XOR từng ký tự với ký tự tương ứng của khóa lặp.
4. Mã hóa kết quả XOR sang định dạng UTF-8, sau đó mã hóa Base64.
5. Gửi lên máy chủ dưới tên tham số là `A`:
   ```text
   A=<CHUOI_BASE64_KET_QUA>
   ```

---

## 3. Cấu Trúc Phản Hồi & Thuật Toán Giải Mã

Khi yêu cầu thành công, máy chủ trả về phong bì JSON có dạng:

```json
{
  "Success": true,
  "Message": "",
  "Data": {
    "B": "CHUOI_DU_LIEU_MA_HOA_BASE64"
  }
}
```

### 3.1. Thuật Toán Giải Mã Phản Hồi (`AD`)
Để khôi phục lại danh sách sự kiện từ `Data.B`:
1. Giải mã Base64 trường `Data.B` sang chuỗi văn bản UTF-8.
2. Thực hiện phép XOR từng ký tự với khóa lặp lại `"AzzSystem"`.
3. Phân tích chuỗi kết quả bằng `json.loads()`.

---

## 4. Cấu Trúc Bản Ghi Sự Kiện Thời Khóa Biểu

Sau khi giải mã, dữ liệu trả về là một mảng JSON chứa các buổi học và buổi thi. Các trường dữ liệu chính:

| Tên Trường | Kiểu Dữ Liệu | Ý Nghĩa | Ví Dụ |
|---|---|---|---|
| `ID` | Chuỗi | Mã số định danh duy nhất của buổi học | `"1058291"` |
| `NGAYHOC` | Chuỗi | Ngày diễn ra buổi học (`DD/MM/YYYY`) | `"18/09/2026"` |
| `GIOBATDAU` | Số / Chuỗi | Giờ bắt đầu (hệ 24 giờ) | `7` |
| `PHUTBATDAU` | Số / Chuỗi | Phút bắt đầu | `0` |
| `GIOKETTHUC` | Số / Chuỗi | Giờ kết thúc | `9` |
| `PHUTKETTHUC`| Số / Chuỗi | Phút kết thúc | `25` |
| `PHANLOAI` | Chuỗi | Phân loại: `LICHHOC` (học) hoặc `LICHTHI` (thi) | `"LICHHOC"` |
| `TENHOCPHAN` | Chuỗi | Tên môn học chính thức | `"An toàn thông tin"` |
| `TENLOPHOCPHAN` | Chuỗi | Tên lớp học phần (có thể chứa thẻ `<br>`) | `"ATTT_K15_02"` |
| `TENPHONGHOC` | Chuỗi | Tên phòng học hoặc phòng thi | `"A2-402"` |
| `PHONGHOC_TEN`| Chuỗi | Tên phòng học dự phòng | `"A2-402"` |
| `GIANGVIEN` | Chuỗi | Họ tên giảng viên giảng dạy | `"ThS. Đỗ Văn B"` |
| `TIETBATDAU` | Số / Chuỗi | Tiết bắt đầu | `1` |
| `TIETKETTHUC`| Số / Chuỗi | Tiết kết thúc | `3` |
| `BUOIHOC` | Chuỗi | Buổi trong ngày | `"Sáng"` |
| `THONGTINCHUYENCAN`| Chuỗi | Ghi chú điểm danh / chuyên cần | `""` |

---

## 5. Quy Chuẩn Làm Sạch Dữ Liệu (Normalization)

Dữ liệu thực tế từ cổng trường thường có một số lỗi định dạng nhỏ mà hàm `normalize_events()` tự động xử lý:

1. **Xóa Thẻ `<br>` Bị Lẫn**: Một số lớp học phần có chèn thẻ `<br>` (ví dụ: `CNTT_K15<br>(N01)`). Hàm sử dụng biểu thức chính quy `re.sub(r"<br\s*/?>", "", text, flags=re.IGNORECASE)` để làm sạch.
2. **Khử Trùng Lặp Bản Ghi**: Đối với các môn có nhiều giảng viên dạy chung hoặc tách nhóm, hệ thống có thể trả về các bản ghi trùng lặp. Mỗi sự kiện được định danh bằng bộ 6 trường duy nhất:
   ```python
   identity = (
       event.get("ID") or "",
       event.get("NGAYHOC"),
       event.get("GIOBATDAU"),
       event.get("PHUTBATDAU"),
       event.get("TENHOCPHAN"),
       event.get("TENLOPHOCPHAN"),
   )
   ```
3. **Sắp Xếp Thời Gian**: Các buổi học được sắp xếp tăng dần theo thời gian bắt đầu, sau đó theo tên môn học.
