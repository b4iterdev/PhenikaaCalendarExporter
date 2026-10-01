# Export Formats & Data Explained

Phenikaa Calendar Exporter generates three distinct file formats during every export. Each format is designed for a specific use case.

---

## 1. Microsoft Excel Workbook (`.xlsx`)

The Excel export is styled for human readability, printing, and academic tracking.

### Sheet 1: `Calendar`
A formatted table (`TableStyleMedium2`) containing every class meeting and exam, sorted chronologically:

| Column Header | Description | Example |
|---|---|---|
| **Date** | Meeting date (`dd/mm/yyyy`) | `15/09/2026` |
| **Weekday** | Day of the week in Vietnamese | `Thứ Ba` |
| **Start** | Starting time (`hh:mm`) | `07:00` |
| **End** | Ending time (`hh:mm`) | `09:25` |
| **Type** | Event category (`Class` or `Exam`) | `Class` |
| **Course** | Course name | `Lập trình mạng` (Network Programming) |
| **Class section** | Academic group and section code | `CNTT_K15_01` |
| **Room / Online** | Physical lecture hall, lab, or virtual link | `A2-304` |
| **Lecturer** | Full name of the professor or teaching assistant | `TS. Nguyễn Văn A` |
| **Periods** | Academic class periods (`TIETBATDAU-TIETKETTHUC`) | `1-3` |
| **Session** | Time of day session | `Sáng` (Morning) |
| **Attendance** | Attendance criteria or notes | `Điểm danh 80%` |
| **Event ID** | Unique university system identifier | `1234567` |

#### Visual Styling Highlights:
- **Exam Highlighting**: Exam rows are highlighted with a soft orange fill (`#FCE4D6`) to distinguish them from standard lectures.
- **Frozen Header**: Row 1 stays pinned when scrolling through hundreds of classes.
- **Auto-Filter**: Filter by lecturer, course name, or day of the week with one click.

### Sheet 2: `Summary`
An executive overview providing immediate analytics:
- **Date range**: Earliest and latest event dates.
- **Total events**: Sum of all scheduled sessions.
- **Class count vs Exam count**: Breakdown of learning vs assessment sessions.
- **Course breakdown**: A table listing every enrolled course and how many meetings are scheduled for each.

---

## 2. iCalendar File (`.ics`)

The `.ics` file adheres strictly to the **RFC 5545** specification and includes full timezone handling:

- **Timezone Declaration**: Embeds `VTIMEZONE` for `Asia/Ho_Chi_Minh` (UTC+07:00).
- **Exam Distinction**: Exam events automatically have their title prefixed with `Exam: ` and are tagged with `CATEGORIES:EXAM`. Normal lectures are tagged with `CATEGORIES:CLASS`.
- **Rich Event Descriptions**: Each calendar event includes:
  ```text
  Class: CNTT_K15_01
  Lecturer: TS. Nguyễn Văn A
  Periods: 1-3
  Attendance: Điểm danh bắt buộc
  ```
- **Consistent UIDs**: UIDs are generated deterministically (`UID:1234567@phenikaa-calendar`) so calendar apps can update existing events instead of creating duplicates.
- **RFC 5545 Folding**: Multi-byte UTF-8 Vietnamese strings are folded cleanly at 75 octets without corrupting characters.

---

## 3. Normalized JSON (`.json`)

The `.json` file contains clean, normalized records directly from the Phenikaa API. It is ideal for developers who want to build their own tools, Discord bots, Notion sync scripts, or mobile widgets.

Example record:
```json
{
  "ID": "1234567",
  "NGAYHOC": "15/09/2026",
  "GIOBATDAU": 7,
  "PHUTBATDAU": 0,
  "GIOKETTHUC": 9,
  "PHUTKETTHUC": 25,
  "PHANLOAI": "LICHHOC",
  "TENHOCPHAN": "Lập trình mạng",
  "TENLOPHOCPHAN": "CNTT_K15_01",
  "TENPHONGHOC": "A2-304",
  "GIANGVIEN": "TS. Nguyễn Văn A",
  "TIETBATDAU": 1,
  "TIETKETTHUC": 3,
  "BUOIHOC": "Sáng",
  "THONGTINCHUYENCAN": ""
}
```
