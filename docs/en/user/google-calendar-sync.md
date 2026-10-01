# Google Calendar Synchronization

One of the most powerful features of Phenikaa Calendar Exporter is automatic one-way synchronization to Google Calendar. Once set up, your class timetable and exam schedule appear seamlessly on your phone, tablet, and smart watch.

---

## Why Synchronize to Google Calendar?

- **Real-Time Notifications**: Get alerts 15–30 minutes before your lectures or exams.
- **Always Up-to-Date**: When university schedules shift (e.g. makeup classes or room changes), the server automatically updates the event in your Google Calendar.
- **Dedicated Calendar Safety**: All events are placed in a dedicated calendar named **`Phenikaa Learning Calendar`**. Your personal, family, and work events are never touched or mixed up!
- **Works Everywhere**: Visible inside Google Calendar on Android, iPhone (iOS), macOS, and the web.

---

## How It Works

```
┌─────────────────────────┐          ┌─────────────────────────┐
│     Phenikaa Portal     │          │  Phenikaa Sync Server   │
│ qldtbeta.phenikaa-uni...│ ───────► │   (Background Worker)   │
└─────────────────────────┘          └────────────┬────────────┘
                                                  │
                                                  │ One-Way Sync
                                                  ▼
                                     ┌─────────────────────────┐
                                     │     Google Calendar     │
                                     │ "Phenikaa Learning Cal" │
                                     └─────────────────────────┘
```

The synchronization is strictly **one-way** (Phenikaa → Google):
- **New events** on Phenikaa are added to Google Calendar.
- **Changed events** (e.g., room change or new teacher) are updated.
- **Cancelled/removed events** are cleanly deleted from the dedicated calendar.
- **Unrelated events** on your Google account are **never touched**.

---

## Setup Steps

### Mode A: If your server uses "Sign in with Google"
This is the simplest setup:
1. Log in to the web app by clicking **Sign in with Google**.
2. When prompted by Google, grant permission to manage calendars created by this app.
3. Link your Phenikaa student portal account on the Dashboard.
4. That's it! Your Google account is already linked, and the server will automatically create your **Phenikaa Learning Calendar** and sync your classes.

### Mode B: If your server uses standard SSO / OIDC Login
1. Sign in to your dashboard with your university account.
2. In the **Google Calendar** section, click **Connect Google Calendar**.
3. A Google authorization page will appear. Log in with the Google account where you want your classes to appear.
4. Review the requested permission:
   - Scope: `calendar.app.created` (This permission only allows the application to manage calendars that it creates itself. It **cannot** view or edit your private calendars!).
5. Approve the connection.
6. The dashboard will show **Connected** and initiate the first sync immediately.

---

## Managing Your Sync

### Viewing Your Events
Open [Google Calendar](https://calendar.google.com). Under **"My calendars"** on the left sidebar, you will see:
- 📅 **Phenikaa Learning Calendar**
You can toggle its visibility on/off, change its color (e.g., university blue or orange), or set default notification times.

### Frequency of Automatic Updates
- The server checks for timetable updates automatically once every 24 hours (or at the custom interval configured by your administrator).
- Need to see changes immediately after registering a new class? Click the **Sync Now** button on your dashboard.

### Pausing Sync
If you are on summer break or want to freeze calendar updates temporarily:
- Click **Pause Sync** on your dashboard.
- Background sync will be paused. Your existing calendar events will stay intact.
- Click **Resume Sync** whenever you are ready.

### Disconnecting & Privacy
If you no longer wish to use the service:
1. Click **Disconnect Google** on your dashboard.
2. The server revokes its access token with Google and removes all linkage records.
3. You can choose to keep or delete the `Phenikaa Learning Calendar` directly inside Google Calendar.
