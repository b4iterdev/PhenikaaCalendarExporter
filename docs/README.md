# Phenikaa Calendar Exporter Documentation

Welcome to the documentation for **Phenikaa Calendar Exporter**!

This project helps students and faculty at Phenikaa University export and synchronize their academic schedules (classes and exam timetables) into standard, portable formats (`.ics`, `.xlsx`, `.json`) and directly into Google Calendar.

---

## 🌐 Choose Your Language / Chọn Ngôn Ngữ

| 🇬🇧 English Documentation | 🇻🇳 Tài liệu Tiếng Việt |
|---|---|
| Complete guides for both everyday users and developers in English. | Hướng dẫn chi tiết, thân thiện cho sinh viên và lập trình viên bằng tiếng Việt. |
| 👉 **[Browse English Docs](en/README.md)** | 👉 **[Xem Tài Liệu Tiếng Việt](vi/README.md)** |

---

## 🎯 Quick Navigation by Audience / Điều Hướng Theo Đối Tượng

### 👤 For End Users / Dành Cho Người Dùng (Sinh viên & Giảng viên)
*Need your schedule on your phone, Google Calendar, or Excel?*

| Guide | Description (EN) | Mô tả (VI) |
|---|---|---|
| **Getting Started** | [Read (EN)](en/user/getting-started.md) | [Đọc (VI)](vi/user/getting-started.md) | Fast introduction, core concepts, and which export method is right for you. |
| **Web Portal & Dashboard** | [Read (EN)](en/user/web-portal.md) | [Đọc (VI)](vi/user/web-portal.md) | Using the web interface: one-shot public export and persistent user dashboard. |
| **Google Calendar Sync** | [Read (EN)](en/user/google-calendar-sync.md) | [Đọc (VI)](vi/user/google-calendar-sync.md) | Automatically sync classes and exams into a dedicated Google Calendar. |
| **Importing Calendar Files** | [Read (EN)](en/user/importing-calendars.md) | [Đọc (VI)](vi/user/importing-calendars.md) | How to import `.ics` files into Apple Calendar, Google Calendar, and Outlook. |
| **Export Formats & Files** | [Read (EN)](en/user/exports-and-formats.md) | [Đọc (VI)](vi/user/exports-and-formats.md) | Detailed explanation of exported `.xlsx` (Excel), `.ics` (iCalendar), and `.json` data. |

---

### 💻 For Developers & Sysadmins / Dành Cho Lập Trình Viên & Quản Trị Viên
*Want to inspect the codebase, self-host with Docker, or reverse engineer the API?*

| Technical Guide | Documentation (EN) | Tài liệu (VI) |
|---|---|---|
| **System Architecture** | [Read (EN)](en/developer/architecture.md) | [Đọc (VI)](vi/developer/architecture.md) | System design, components, data flow, and security model. |
| **CLI Reference** | [Read (EN)](en/developer/cli-reference.md) | [Đọc (VI)](vi/developer/cli-reference.md) | Complete CLI flags, authentication sources, date options, and output control. |
| **Authentication Internals** | [Read (EN)](en/developer/authentication-internals.md) | [Đọc (VI)](vi/developer/authentication-internals.md) | Reverse-engineered XOR bootstrap cipher, Playwright credential capture, token handling. |
| **Phenikaa API Protocol** | [Read (EN)](en/developer/api-protocol.md) | [Đọc (VI)](vi/developer/api-protocol.md) | Reverse-engineered payload obfuscation (`AE`/`AD`), endpoints, and schema. |
| **Server & Docker Deployment** | [Read (EN)](en/developer/server-deployment.md) | [Đọc (VI)](vi/developer/server-deployment.md) | Production deployment, Docker, OIDC/Google OAuth configuration, Fernet encryption. |
| **Testing & Contributing** | [Read (EN)](en/developer/testing-and-contributing.md) | [Đọc (VI)](vi/developer/testing-and-contributing.md) | Running unit tests, test matrix, regression safeguards, and coding guidelines. |

---

### ❓ Troubleshooting & Support / Xử Lý Sự Cố
- 🇬🇧 **[English Troubleshooting Guide](en/troubleshooting.md)**: Session expiration (`401`), Playwright issues, empty schedule ranges, time zone offsets.
- 🇻🇳 **[Hướng Dẫn Xử Lý Sự Cố (Tiếng Việt)](vi/troubleshooting.md)**: Khắc phục lỗi hết hạn phiên, sự cố Playwright, lịch trống, sai múi giờ.

---

## 🔒 Privacy & Safety Guarantee

1. **No Password Storage**: The application never asks for, types, or stores your student portal password.
2. **Local Execution**: All processing happens on your local machine or your private self-hosted server.
3. **Encrypted Storage**: Sensitive bearer tokens and Google credentials are encrypted with AES-128-CBC (Fernet) at rest.
4. **Scoped Access**: Google Calendar integration requests only permission to manage the dedicated *"Phenikaa Learning Calendar"*, leaving the rest of your calendars untouched.
