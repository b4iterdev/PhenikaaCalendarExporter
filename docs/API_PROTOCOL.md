# Phenikaa calendar API protocol

This document records the behavior reverse-engineered from the portal's own JavaScript on 26 August 2026. It is an internal API, not a published public contract, so paths, action names and encoding may change.

## Source application

- Portal: `https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx#lichhoc`
- Calendar module HTML: `/congsinhvien/ApisCongSinhVien/modules/thoikhoabieu/html/lichhoc.html`
- Calendar JavaScript: `/congsinhvien/ApisCongSinhVien/modules/thoikhoabieu/script/lichgiang.js`
- API configuration: `/congsinhvien/Config.js`
- Request implementation: `/congsinhvien/Core/systemroot.js`
- Encoding helpers: `/congsinhvien/assets/js/crypto-js.js`

## Authentication bootstrap

After a successful Microsoft/Phenikaa login, the authenticated `index.aspx` response contains a function like:

```html
<script>AXYZCLRVN = () => "BASE64_DATA"</script>
```

The value is decoded by the site's `AD(value, "AzzS")` helper:

1. Base64-decode to UTF-8 text.
2. XOR each JavaScript character with the repeating key `AzzS`.
3. Parse the result as JSON.

Required fields:

```json
{
  "userId": "internal 32-character ID",
  "tokenJWT": "short-lived bearer token"
}
```

The exporter supports three authentication sources:

1. `--cache-dir`: recover the newest authenticated index response from a Chromium `Cache_Data` directory.
2. `--bootstrap-html`: parse a locally saved authenticated index response.
3. `--auth-json`: read a private JSON file containing `userId` and `tokenJWT`.

## Calendar request

### Endpoint

```text
POST https://qldtbeta.phenikaa-uni.edu.vn/sinhvienapi3/api/SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv
```

### Headers

```text
Authorization: Bearer <tokenJWT>
Content-Type: application/x-www-form-urlencoded; charset=UTF-8
Accept: application/json
Origin: https://qldtbeta.phenikaa-uni.edu.vn
Referer: https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx
```

### Plain request object

```json
{
  "action": "SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv",
  "func": "pkg_congthongtin_hssv_thongtin.LayDSLichCaNhan",
  "iM": "AzzSystem",
  "strQLSV_NguoiHoc_Id": "<userId>",
  "strNgayBatDau": "01/08/2026",
  "strNgayKetThuc": "31/10/2026",
  "strChucNang_Id": "",
  "strNguoiThucHien_Id": "<userId>"
}
```

Dates are inclusive and use `DD/MM/YYYY`.

### Request encoding

The portal calls `AE(JSON.stringify(payload), actionSuffix)`, where:

```text
actionSuffix = DSA4BRINKCIpAiAPKSAv
```

`AE` performs repeating-key XOR over JavaScript characters, UTF-8 encodes the XOR result, and Base64 encodes it. The POST body is form-encoded:

```text
A=<encoded payload>
```

This is obfuscation, not cryptographic protection. HTTPS and the bearer token provide transport/authentication security.

## Calendar response

A successful outer response resembles:

```json
{
  "Success": true,
  "Message": "",
  "Data": {"B": "BASE64_DATA"}
}
```

Decode `Data.B` using repeating-key XOR with `AzzSystem`, then parse JSON. The result is an array of calendar records.

Important fields include:

| Field | Meaning |
|---|---|
| `ID` | Unique meeting/event identifier |
| `NGAYHOC` | Meeting date, `DD/MM/YYYY` |
| `GIOBATDAU`, `PHUTBATDAU` | Start hour/minute |
| `GIOKETTHUC`, `PHUTKETTHUC` | End hour/minute |
| `PHANLOAI` | `LICHHOC` or `LICHTHI` |
| `TENHOCPHAN` | Course name |
| `TENLOPHOCPHAN` | Course-section display name; may contain `<br>` |
| `TENPHONGHOC` / `PHONGHOC_TEN` | Room or online location |
| `GIANGVIEN` | Lecturer |
| `TIETBATDAU`, `TIETKETTHUC` | First/last teaching period |
| `THONGTINCHUYENCAN` | Attendance information, when present |

## Failure behavior

- HTTP `401`: session expired or was invalidated; sign in again.
- `Success: false`: surface the server's `Message`.
- Missing `Data.B` is tolerated only if `Data` is already a list.
- Empty results may mean a genuinely empty range, the wrong date range, or an expired/changed backend contract.

## Current-semester discovery

The API requires explicit dates and does not expose a semester selector in this flow. Use a deliberately broad range that covers the expected semester, such as August through January, then inspect the first and last returned event dates. Do not infer semester boundaries solely from today's date.
