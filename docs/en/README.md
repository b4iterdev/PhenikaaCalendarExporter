# English Documentation

Welcome to the English documentation for **Phenikaa Calendar Exporter**.

This repository provides tools to extract your academic timetable from the Phenikaa University student portal (`qldtbeta.phenikaa-uni.edu.vn`) and export or sync it into modern calendar applications.

---

## 📚 Table of Contents

### 👤 User Guides
Designed for students and faculty who want their calendar exported or synced without writing code.

1. **[Getting Started](user/getting-started.md)**  
   What the exporter does, key benefits, and choosing the right method for you.
2. **[Web Portal & Dashboard](user/web-portal.md)**  
   Exporting your calendar via the web interface: one-shot downloads and background sync.
3. **[Google Calendar Sync](user/google-calendar-sync.md)**  
   Setting up automatic, one-way synchronization to a dedicated Google Calendar.
4. **[Importing into Calendar Apps](user/importing-calendars.md)**  
   How to import `.ics` files into Apple Calendar, Google Calendar, and Microsoft Outlook.
5. **[Export Formats Explained](user/exports-and-formats.md)**  
   Understanding `.xlsx` (Excel), `.ics` (iCal), and `.json` data fields.

---

### 💻 Developer Guides
Designed for developers, self-hosters, and system administrators.

1. **[System Architecture](developer/architecture.md)**  
   High-level overview, component interactions, and execution flow.
2. **[CLI Reference](developer/cli-reference.md)**  
   Complete command-line parameters, options, and usage examples.
3. **[Authentication Internals](developer/authentication-internals.md)**  
   Reverse-engineered XOR cipher, `AXYZCLRVN` bootstrap, and token capture.
4. **[Internal API Protocol](developer/api-protocol.md)**  
   End-to-end specification of the Phenikaa portal endpoints and request obfuscation.
5. **[Server & Docker Deployment](developer/server-deployment.md)**  
   Deploying the web app with Docker, OIDC/Google OAuth configuration, and data persistence.
6. **[Testing & Contributing](developer/testing-and-contributing.md)**  
   Running the test suite, test coverage, and contribution guidelines.

---

### ❓ Troubleshooting
- **[Troubleshooting Guide](troubleshooting.md)**  
  Common errors (HTTP 401, session timeouts, missing events, time zone shifts) and how to resolve them.
