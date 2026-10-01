# Web Portal & Dashboard Guide

The web interface makes exporting and managing your university schedule straightforward without touching any command-line tools.

---

## 1. Quick One-Shot Export (No Account Needed)

If you just want to download your schedule once into Excel or your phone's calendar, you don't even need to create an account on the server.

1. Navigate to the server homepage (e.g., `https://calendar.example.edu`).
2. Make sure you are on the **Public Export** tab.
3. Select your desired date range (usually start of the semester to end of exams, e.g., `01/08/2026` to `31/01/2027`).
4. Provide your authentication information using one of two methods:

### Method A: Saved `index.aspx` Page (Easiest)
1. Open Chrome, Edge, or Firefox and log in to the Phenikaa portal: `https://qldtbeta.phenikaa-uni.edu.vn`.
2. Go to your calendar tab (`#lichhoc`).
3. Press **Ctrl + S** (Windows) or **Cmd + S** (Mac) to save the webpage. Choose **"Webpage, HTML Only"** and save `index.aspx` (or `index.html`).
4. On the Public Export page, select **"Saved authenticated HTML"** and upload or paste the file contents.
5. Click **Download Calendar**.

> **Note**: This file contains a temporary login token (`AXYZCLRVN`). The server uses it immediately in memory to download your schedule, returns your `.zip` file, and immediately deletes it. Nothing is stored in the database.

### Method B: Manual User ID & Token
1. In the logged-in student portal, open Developer Tools (**F12**) → **Console**.
2. Run `window.edu?.system?.userId` to find your 32-character ID.
3. Switch to the **Network** tab, click any calendar request, and copy the Bearer token without the `"Bearer "` prefix.
4. Paste both into the manual fields and click **Download Calendar**.

---

## 2. Using the Dashboard (With Account)

Creating an account allows the server to keep your timetable synchronized automatically with Google Calendar or keep fresh calendar downloads available.

### Logging In
1. Click **Sign in** in the top-right corner.
2. Sign in using your organization's login (Google or university single-sign-on / OIDC).
3. You will be redirected to your personal **Dashboard**.

### Connecting Your Phenikaa Account
The server needs to link your Phenikaa student profile once:
1. On your Dashboard, click **Connect Phenikaa Account**.
2. A remote login window will open showing the official Phenikaa login page.
3. Sign in with your university Microsoft account as usual, completing any two-factor verification (SMS/Authenticator).
4. Once logged in, the window will automatically detect your session, close, and mark your account as **Active (Connected)**.

> **Security Note**: The server captures your session tokens just like your browser does. It never records your password.

---

## 3. Dashboard Features

Once connected, your dashboard shows:

- **Schedule Overview**: Total number of classes, exam count, and semester date span.
- **Sync Status**: Last successful synchronization time and status (`Active`, `Attention needed`, or `Action required`).
- **Download Export Files**: Download your updated `calendar.ics`, `calendar.xlsx`, and `calendar.json` anytime with a single click.
- **Manual Sync**: Click **Sync Now** to immediately check for timetable changes from the university.
- **Pause / Resume Sync**: Temporarily pause background updates if needed.
- **Disconnect**: Revoke access and wipe your stored session tokens with one click.

---

## 4. Language Settings

The web interface is fully bilingual:
- Click the language switcher in the header to toggle between **English** and **Tiếng Việt**.
- Your preference is saved in a lightweight cookie.
