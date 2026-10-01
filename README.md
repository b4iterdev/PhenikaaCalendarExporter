# Phenikaa Calendar Exporter

A reproducible command-line project that reads the authenticated Phenikaa student-calendar API and exports:

- `.xlsx` - formatted Excel calendar plus summary sheet.
- `.ics` - timezone-aware calendar import for Apple Calendar, Google Calendar and Outlook.
- `.json` - normalized source records for auditing and future processing.

Server mode can optionally connect a session to Google Calendar for one-way Phenikaa-to-Google sync into a dedicated app-created calendar; see [Server and Docker deployment](docs/SERVER.md).

Use `PHENIKAA_SERVER_AUTH=google` for Google app login with the same account automatically used for Calendar sync. Users then only need to connect their Phenikaa account. External OIDC login remains available as the default mode; see [Google login setup](docs/SERVER.md#google-login-mode).

The project does not store passwords or enter credentials on your behalf. It reads session data from your own authenticated browser.

## Requirements

- Python 3.9 or newer.
- Network access to `qldtbeta.phenikaa-uni.edu.vn`.
- A currently authenticated Phenikaa portal session.
- `openpyxl` 3.1.5 for Excel output.
- Optional `playwright` and Chromium for automated browser login.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
python -m pip install -e .
```

Without installation, invoke `python phenikaa_exporter.py ...` directly.

## Documentation

Comprehensive, modular documentation tailored for both **end users** (students & lecturers) and **developers**:

- 📖 **[Documentation Hub](docs/README.md)** (Central index with language switcher)
- 🇬🇧 **[English Documentation](docs/en/README.md)**:
  - 👤 **User Guides**: [Getting Started](docs/en/user/getting-started.md) · [Web Portal](docs/en/user/web-portal.md) · [Google Calendar Sync](docs/en/user/google-calendar-sync.md) · [Importing Calendars](docs/en/user/importing-calendars.md) · [Export Formats](docs/en/user/exports-and-formats.md)
  - 💻 **Developer Guides**: [Architecture](docs/en/developer/architecture.md) · [CLI Reference](docs/en/developer/cli-reference.md) · [Auth Internals](docs/en/developer/authentication-internals.md) · [API Protocol](docs/en/developer/api-protocol.md) · [Server & Docker](docs/en/developer/server-deployment.md) · [Testing & Contributing](docs/en/developer/testing-and-contributing.md)
  - ❓ [Troubleshooting & FAQ](docs/en/troubleshooting.md)
- 🇻🇳 **[Tài Liệu Tiếng Việt](docs/vi/README.md)**:
  - 👤 **Hướng dẫn Người dùng**: [Bắt đầu nhanh](docs/vi/user/getting-started.md) · [Cổng Web](docs/vi/user/web-portal.md) · [Đồng bộ Google](docs/vi/user/google-calendar-sync.md) · [Nhập file .ics](docs/vi/user/importing-calendars.md) · [Tìm hiểu các file xuất](docs/vi/user/exports-and-formats.md)
  - 💻 **Hướng dẫn Lập trình viên**: [Kiến trúc](docs/vi/developer/architecture.md) · [Tham chiếu CLI](docs/vi/developer/cli-reference.md) · [Cơ chế xác thực](docs/vi/developer/authentication-internals.md) · [Giao thức API](docs/vi/developer/api-protocol.md) · [Triển khai Server & Docker](docs/vi/developer/server-deployment.md) · [Kiểm thử](docs/vi/developer/testing-and-contributing.md)
  - ❓ [Xử lý sự cố](docs/vi/troubleshooting.md)
- 🛡️ [Security guidance](SECURITY.md)

## Tests

```bash
python -m unittest discover -s tests -v
```

## Known limitations

- The API is internal and may change without notice.
- Authentication expires; the project never stores passwords or types credentials.
- “Current semester” is represented by an explicit broad date range, not official semester metadata.
- Generated exports contain private academic information and are ignored by Git by default.

## Verification

The API workflow was verified against the logged-in student portal on 26 August 2026. A current-semester request returned 70 events covering 4 August–28 October 2026: 65 classes and 5 exams. Tests cover encryption/decryption, browser-cache extraction, login capture, API exchange, deduplication, XLSX, ICS, UTF-8 folding, and CLI output.
