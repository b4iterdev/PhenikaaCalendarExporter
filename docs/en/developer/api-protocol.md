# Internal API Protocol Specification

This document details the reverse-engineered wire protocol used by the Phenikaa University student portal (`qldtbeta.phenikaa-uni.edu.vn`) for retrieving personal timetables.

> **Disclaimer**: This is an internal, unpublished university API. The endpoints, encryption keys, and request actions described here were reverse-engineered from client-side JavaScript assets (`Core/systemroot.js`, `modules/thoikhoabieu/script/lichgiang.js`) and may change during university portal updates.

---

## 1. Calendar Query Endpoint

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

## 2. Request Obfuscation & Encoding

The API does not receive plain JSON. Instead, the portal obfuscates payloads client-side using a custom repeating-key XOR algorithm before submitting them as standard form data (`application/x-www-form-urlencoded`).

### 2.1. Plain Request Payload

```json
{
  "action": "SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv",
  "func": "pkg_congthongtin_hssv_thongtin.LayDSLichCaNhan",
  "iM": "AzzSystem",
  "strQLSV_NguoiHoc_Id": "<32_CHAR_USER_ID>",
  "strNgayBatDau": "01/08/2026",
  "strNgayKetThuc": "31/01/2027",
  "strChucNang_Id": "",
  "strNguoiThucHien_Id": "<32_CHAR_USER_ID>"
}
```

*Note: Dates must be formatted as `DD/MM/YYYY`.*

### 2.2. Obfuscation Function (`AE`)

1. Extract the encryption key from the action suffix:
   ```python
   CALENDAR_ACTION = "SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv"
   KEY = CALENDAR_ACTION.split("/", 1)[1]  # "DSA4BRINKCIpAiAPKSAv"
   ```
2. Serialize JSON string with compact delimiters (no spaces: `separators=(',', ':')`).
3. For each character in the string, compute XOR with the repeating key character.
4. UTF-8 encode the XOR-transformed characters, then Base64 encode the result.
5. Form-encode under parameter name `A`:
   ```text
   A=<BASE64_XOR_RESULT>
   ```

---

## 3. Response Structure & Decryption

A successful HTTP 200 response returns an outer JSON envelope:

```json
{
  "Success": true,
  "Message": "",
  "Data": {
    "B": "BASE64_OBFUSCATED_PAYLOAD"
  }
}
```

### 3.1. Response Decryption Function (`AD`)
To recover the actual calendar records from `Data.B`:
1. Base64 decode `Data.B` to UTF-8 text.
2. XOR each character with the repeating key `"AzzSystem"`.
3. Parse the decrypted string with `json.loads()`.

---

## 4. Calendar Event Schema

The decrypted payload is a JSON array of event objects. Key fields:

| Field Name | Type | Description | Example |
|---|---|---|---|
| `ID` | String | Unique schedule meeting identifier | `"1058291"` |
| `NGAYHOC` | String | Meeting date in `DD/MM/YYYY` format | `"18/09/2026"` |
| `GIOBATDAU` | Integer/String | Starting hour (24-hour clock) | `7` |
| `PHUTBATDAU` | Integer/String | Starting minute | `0` |
| `GIOKETTHUC` | Integer/String | Ending hour | `9` |
| `PHUTKETTHUC` | Integer/String | Ending minute | `25` |
| `PHANLOAI` | String | Event classification: `LICHHOC` (class) or `LICHTHI` (exam) | `"LICHHOC"` |
| `TENHOCPHAN` | String | Official course title | `"An toàn thông tin"` |
| `TENLOPHOCPHAN` | String | Class section name (may contain HTML `<br>`) | `"ATTT_K15_02"` |
| `TENPHONGHOC` | String | Classroom or lab identifier | `"A2-402"` |
| `PHONGHOC_TEN` | String | Fallback classroom identifier | `"A2-402"` |
| `GIANGVIEN` | String | Name of instructor | `"ThS. Đỗ Văn B"` |
| `TIETBATDAU` | Integer/String | First teaching period | `1` |
| `TIETKETTHUC` | Integer/String | Last teaching period | `3` |
| `BUOIHOC` | String | Time of day session | `"Sáng"` |
| `THONGTINCHUYENCAN`| String | Attendance requirements or record | `""` |

---

## 5. Event Normalization & Edge Cases

The portal's data often contains minor formatting quirks that the exporter automatically sanitizes in `normalize_events()`:

1. **HTML `<br>` Tags**: Some course section names contain `<br>` or `<br/>` tags (e.g. `CNTT_K15<br>(N01)`). These are stripped with regex `re.sub(r"<br\s*/?>", "", text, flags=re.IGNORECASE)`.
2. **Duplicate Records**: The portal occasionally returns duplicate meeting records for team-taught courses or split sections. Events are deduplicated using a 6-element tuple:
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
3. **Chronological Sorting**: Normalized events are sorted by starting datetime, then by course name.
