# Importing Calendars (.ics) into Your Devices

When you download your schedule from the CLI or the Public Export page, you get a standard `.ics` (iCalendar) file. This file can be imported into virtually every calendar app in the world.

---

## 💡 Best Practice: Create a Separate Calendar First!

Before importing, **create a new, dedicated calendar** (e.g., named *"Phenikaa Semester 1"*) in your calendar app.

> **Why?** If you import hundreds of class meetings into your main calendar by mistake, deleting them one-by-one is tedious. By importing into a separate calendar, you can hide it with one checkmark or delete the entire semester in one click when finished!

---

## 1. Google Calendar (Web, Android, iOS)

### On Computer (Web Browser):
1. Go to [calendar.google.com](https://calendar.google.com).
2. On the left sidebar, click the **`+`** icon next to **"Other calendars"** → Select **Create new calendar**.
3. Name it `Phenikaa University` (or similar) and click **Create calendar**.
4. Click the gear icon (⚙️) in the top-right → **Settings**.
5. In the left menu, select **Import & export** → **Import**.
6. Click **Select file from your computer** and choose your exported `.ics` file.
7. Under **Add to calendar**, be sure to choose the `Phenikaa University` calendar you created in step 2.
8. Click **Import**.

### On Android or iPhone:
Once imported via the web browser, open the Google Calendar app on your phone, open Settings, tap your account, and ensure the new calendar has **Sync** switched on.

---

## 2. Apple Calendar (iPhone, iPad, Mac)

### On Mac:
1. Open the **Calendar** app.
2. Go to **File** → **New Calendar** and name it `Phenikaa`.
3. Double-click the exported `.ics` file, or drag-and-drop it into the Calendar app window.
4. When prompted which calendar to add the events to, select `Phenikaa`.
5. If iCloud sync is enabled, all events will automatically appear on your iPhone and iPad!

### Directly on iPhone / iPad:
1. Send the `.ics` file to your phone via AirDrop, Telegram, Email, or save it to the Files app.
2. Tap the `.ics` file.
3. iOS will show a preview of all events. Tap **Add All**.
4. Choose an existing calendar or tap **New Calendar** to keep school classes organized separately.

---

## 3. Microsoft Outlook (Windows, Mac, Web)

### Outlook Web (Office 365 / Student Email):
1. Log in to [outlook.office.com/calendar](https://outlook.office.com/calendar).
2. In the left navigation pane, click **Add calendar**.
3. Select **Upload from file**.
4. Browse and select your `.ics` file.
5. Choose or create a target calendar and click **Import**.

### Outlook Desktop (Windows / Mac):
1. Go to **File** → **Open & Export** → **Open Calendar (.ics)**.
2. Select your `.ics` file.
3. Click **Open as New** (recommended) so it creates an isolated side-by-side calendar.

---

## ⏰ Timezone & Notification Reminders

- **Timezone**: All exported events are explicitly tagged with `TZID:Asia/Ho_Chi_Minh` (UTC+07:00). When you travel abroad or change your device timezone, calendar apps will adjust automatically.
- **Reminders**: By default, `.ics` files let your device's calendar app choose when to notify you. You can configure notifications (e.g., 30 minutes before class) in your calendar application settings.
- **Exams**: All exam events are prefixed with **`Exam:`** and marked with the `EXAM` category for quick visual search.
