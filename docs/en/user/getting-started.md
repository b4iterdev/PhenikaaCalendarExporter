# Getting Started

Welcome! **Phenikaa Calendar Exporter** helps students and instructors at Phenikaa University easily transfer their class schedules and exam timetables into calendar apps on phones, computers, and tablets.

---

## Why Use This Tool?

Normally, viewing your timetable requires logging into `qldtbeta.phenikaa-uni.edu.vn`, navigating through tables, and manually noting down every lecture, room change, and exam date. 

With this tool:
- **No manual entry**: Automatically export an entire semester of classes in seconds.
- **Never miss a class or exam**: Get notifications on your phone or smartwatch before each session starts.
- **Room and lecturer details included**: Every calendar event includes class name, section, classroom, teacher name, period, and attendance notes.
- **Always private & secure**: The tool never asks for or stores your university password.

---

## Choose Your Method

Depending on your preference and setup, you can use Phenikaa Calendar Exporter in two ways:

```
┌────────────────────────────────────────────────────────┐
│             Phenikaa Calendar Exporter                 │
└───────────────────────────┬────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
    [ Web Interface ]               [ Command Line (CLI) ]
   • Best for everyone             • Best for programmers
   • Point-and-click               • Direct terminal tool
   • Optional Google Sync          • Fast local file export
   • Mobile friendly               • No server needed
```

### Option 1: Web Interface (Recommended for most users)
If your school club or lab hosts an instance of the Phenikaa Calendar Server:
1. Open the website in your browser.
2. Choose **Public Export** for a one-time download of your `.ics` or `.xlsx` file, or **Sign in** to set up automatic background sync with Google Calendar.
3. 👉 Read the **[Web Portal Guide](web-portal.md)** for step-by-step instructions.

### Option 2: Command-Line Interface (CLI)
If you have Python installed on your computer and want to run the tool locally:
1. Clone the repository and install dependencies.
2. Run `python phenikaa_exporter.py --browser-login ...` to open a sign-in window and export your calendar files directly to your computer.
3. 👉 Read the **[CLI Reference](../developer/cli-reference.md)** for commands and options.

---

## What You Get

Every export generates three files:

| File Format | Best For | What it Contains |
|---|---|---|
| **`.ics`** | Apple Calendar, Google Calendar, Outlook | Standard calendar file with exact start/end times, room locations, and reminders. |
| **`.xlsx`** | Microsoft Excel, Google Sheets, Printing | Beautifully formatted spreadsheet with colored headers, exam highlights, and summary statistics. |
| **`.json`** | Developers, automation tools | Raw structured data containing all details from the school database. |

👉 Learn more about these files in **[Export Formats Explained](exports-and-formats.md)**.

---

## Next Steps

- Want to export your calendar right now? Check out **[Web Portal Guide](web-portal.md)**.
- Want automatic sync to your Google account? See **[Google Calendar Sync](google-calendar-sync.md)**.
- Have a `.ics` file and want to load it on iPhone or Android? See **[Importing into Calendar Apps](importing-calendars.md)**.
