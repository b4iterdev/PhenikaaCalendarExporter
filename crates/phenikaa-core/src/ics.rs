use crate::crypto::TIMEZONE;
use crate::models::{normalize_events, CalendarEvent};
use chrono::Utc;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::Path;

pub fn ics_escape(val: &str) -> String {
    val.replace('\\', "\\\\")
        .replace(';', "\\;")
        .replace(',', "\\,")
        .replace('\r', "")
        .replace('\n', "\\n")
}

pub fn ics_fold(line: &str) -> String {
    let bytes = line.as_bytes();
    if bytes.len() <= 75 {
        return line.to_string();
    }

    let mut out_parts = Vec::new();
    let mut cur: Vec<u8> = bytes.to_vec();

    while cur.len() > 75 {
        let mut cut = 75;
        // Don't cut in the middle of a multi-byte UTF-8 sequence (continuation byte: 0b10xxxxxx)
        while cut > 0 && (cur[cut] & 0xC0) == 0x80 {
            cut -= 1;
        }
        out_parts.push(String::from_utf8_lossy(&cur[..cut]).to_string());
        let mut next = vec![b' '];
        next.extend_from_slice(&cur[cut..]);
        cur = next;
    }
    out_parts.push(String::from_utf8_lossy(&cur).to_string());
    out_parts.join("\r\n")
}

pub fn generate_ics(events: &[CalendarEvent], calendar_name: &str) -> String {
    let normalized = normalize_events(events.to_vec());
    let mut lines = vec![
        "BEGIN:VCALENDAR".to_string(),
        "VERSION:2.0".to_string(),
        "PRODID:-//Phenikaa Calendar Exporter//EN".to_string(),
        "CALSCALE:GREGORIAN".to_string(),
        "METHOD:PUBLISH".to_string(),
        format!("X-WR-CALNAME:{}", ics_escape(calendar_name)),
        format!("X-WR-TIMEZONE:{TIMEZONE}"),
        "BEGIN:VTIMEZONE".to_string(),
        format!("TZID:{TIMEZONE}"),
        format!("X-LIC-LOCATION:{TIMEZONE}"),
        "BEGIN:STANDARD".to_string(),
        "TZOFFSETFROM:+0700".to_string(),
        "TZOFFSETTO:+0700".to_string(),
        "TZNAME:+07".to_string(),
        "DTSTART:19700101T000000".to_string(),
        "END:STANDARD".to_string(),
        "END:VTIMEZONE".to_string(),
    ];

    let stamp = Utc::now().format("%Y%m%dT%H%M%SZ").to_string();

    for ev in &normalized {
        let start = match ev.start_datetime() {
            Some(dt) => dt,
            None => continue,
        };
        let end = match ev.end_datetime() {
            Some(dt) => dt,
            None => continue,
        };

        let is_exam = ev.is_exam();
        let course = ev.course_name();
        let summary = if is_exam {
            format!("Exam: {course}")
        } else {
            course.clone()
        };

        let section = ev.section_name();
        let room = ev.room();
        let lecturer = ev.lecturer();

        let mut desc_parts = Vec::new();
        if !section.is_empty() {
            desc_parts.push(format!("Class: {section}"));
        }
        if !lecturer.is_empty() {
            desc_parts.push(format!("Lecturer: {lecturer}"));
        }
        let periods = ev.periods_string();
        if !periods.is_empty() {
            desc_parts.push(format!("Periods: {periods}"));
        }
        let attendance = ev.attendance();
        if !attendance.is_empty() {
            desc_parts.push(format!("Attendance: {attendance}"));
        }
        let description = desc_parts.join("\n");

        let uid = if let Some(ref id) = ev.id {
            let clean = crate::models::clean_html_breaks(Some(id));
            if clean.is_empty() {
                let hash_input = format!("{}{}{}", summary, start.format("%Y-%m-%dT%H:%M:%S"), room);
                let mut hasher = Sha256::new();
                hasher.update(hash_input.as_bytes());
                format!("{:x}", hasher.finalize())
            } else {
                clean
            }
        } else {
            let hash_input = format!("{}{}{}", summary, start.format("%Y-%m-%dT%H:%M:%S"), room);
            let mut hasher = Sha256::new();
            hasher.update(hash_input.as_bytes());
            format!("{:x}", hasher.finalize())
        };

        lines.push("BEGIN:VEVENT".to_string());
        lines.push(format!("UID:{uid}@phenikaa-calendar"));
        lines.push(format!("DTSTAMP:{stamp}"));
        lines.push(format!("DTSTART;TZID={TIMEZONE}:{}", start.format("%Y%m%dT%H%M%S")));
        lines.push(format!("DTEND;TZID={TIMEZONE}:{}", end.format("%Y%m%dT%H%M%S")));
        lines.push(format!("SUMMARY:{}", ics_escape(&summary)));
        lines.push(format!("LOCATION:{}", ics_escape(&room)));
        lines.push(format!("DESCRIPTION:{}", ics_escape(&description)));
        lines.push(format!("CATEGORIES:{}", if is_exam { "EXAM" } else { "CLASS" }));
        lines.push("STATUS:CONFIRMED".to_string());
        lines.push("TRANSP:OPAQUE".to_string());
        lines.push("END:VEVENT".to_string());
    }

    lines.push("END:VCALENDAR".to_string());

    let folded: Vec<String> = lines.iter().map(|l| ics_fold(l)).collect();
    folded.join("\r\n") + "\r\n"
}

pub fn write_ics<P: AsRef<Path>>(
    path: P,
    events: &[CalendarEvent],
    calendar_name: &str,
) -> std::io::Result<()> {
    let content = generate_ics(events, calendar_name);
    let p = path.as_ref();
    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent)?;
    }
    fs::write(p, content.as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ics_folding_and_structure() {
        let raw = r#"[
            {
                "ID": "class-1",
                "TENHOCPHAN": "Học máy nâng cao",
                "TENLOPHOCPHAN": "Học máy nâng cao(N01)",
                "NGAYHOC": "24/08/2026",
                "GIOBATDAU": 6.0,
                "PHUTBATDAU": 45.0,
                "GIOKETTHUC": 9.0,
                "PHUTKETTHUC": 25.0,
                "TIETBATDAU": 1.0,
                "TIETKETTHUC": 3.0,
                "TENPHONGHOC": "A1-601",
                "GIANGVIEN": "Phạm Tiến Lâm",
                "PHANLOAI": "LICHHOC"
            },
            {
                "ID": "exam-1",
                "TENHOCPHAN": "Kiến trúc máy tính",
                "DANGKY_LOPHOCPHAN_TEN": "Thi cuối kỳ",
                "NGAYHOC": "28/10/2026",
                "GIOBATDAU": 9.0,
                "PHUTBATDAU": 0.0,
                "GIOKETTHUC": 10.0,
                "PHUTKETTHUC": 0.0,
                "PHONGHOC_TEN": "A2-402",
                "PHANLOAI": "LICHTHI"
            }
        ]"#;
        let events: Vec<CalendarEvent> = serde_json::from_str(raw).unwrap();
        let ics = generate_ics(&events, "Test");

        assert!(ics.contains("BEGIN:VCALENDAR"));
        assert!(ics.contains("DTSTART;TZID=Asia/Ho_Chi_Minh:20260824T064500"));
        assert!(ics.contains("SUMMARY:Exam: Kiến trúc máy tính"));
        assert_eq!(ics.matches("BEGIN:VEVENT").count(), 2);

        for line in ics.split("\r\n") {
            assert!(line.as_bytes().len() <= 75, "line too long: {}", line);
        }
    }
}
