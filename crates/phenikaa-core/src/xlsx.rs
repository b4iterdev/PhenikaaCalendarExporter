use crate::models::{normalize_events, CalendarEvent};
use chrono::Datelike;
use rust_xlsxwriter::{
    Color, Format, FormatAlign, FormatBorder, Table, TableStyle, Workbook, XlsxError,
};
use std::collections::{BTreeMap, HashSet};
use std::path::Path;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum XlsxExportError {
    #[error("cannot create an XLSX export with no events")]
    EmptyEvents,
    #[error("xlsx writer error: {0}")]
    Writer(#[from] XlsxError),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub fn write_xlsx<P: AsRef<Path>>(path: P, events: &[CalendarEvent]) -> Result<(), XlsxExportError> {
    let normalized = normalize_events(events.to_vec());
    if normalized.is_empty() {
        return Err(XlsxExportError::EmptyEvents);
    }

    let mut workbook = Workbook::new();

    // 1. Calendar worksheet
    let calendar = workbook.add_worksheet();
    calendar.set_name("Calendar")?;

    let navy = Color::RGB(0x17365D);
    let exam_fill = Color::RGB(0xFCE4D6);
    let border_color = Color::RGB(0xD9E1F2);

    let header_fmt = Format::new()
        .set_background_color(navy)
        .set_font_color(Color::RGB(0xFFFFFF))
        .set_bold()
        .set_align(FormatAlign::Center)
        .set_align(FormatAlign::VerticalCenter);

    let default_row_fmt = Format::new()
        .set_border_bottom(FormatBorder::Thin)
        .set_border_bottom_color(border_color)
        .set_align(FormatAlign::Top)
        .set_text_wrap();

    let date_fmt = Format::new()
        .set_border_bottom(FormatBorder::Thin)
        .set_border_bottom_color(border_color)
        .set_align(FormatAlign::Top)
        .set_num_format("dd/mm/yyyy");

    let time_fmt = Format::new()
        .set_border_bottom(FormatBorder::Thin)
        .set_border_bottom_color(border_color)
        .set_align(FormatAlign::Top)
        .set_num_format("hh:mm");

    let exam_row_fmt = Format::new()
        .set_background_color(exam_fill)
        .set_border_bottom(FormatBorder::Thin)
        .set_border_bottom_color(border_color)
        .set_align(FormatAlign::Top)
        .set_text_wrap();

    let exam_date_fmt = Format::new()
        .set_background_color(exam_fill)
        .set_border_bottom(FormatBorder::Thin)
        .set_border_bottom_color(border_color)
        .set_align(FormatAlign::Top)
        .set_num_format("dd/mm/yyyy");

    let exam_time_fmt = Format::new()
        .set_background_color(exam_fill)
        .set_border_bottom(FormatBorder::Thin)
        .set_border_bottom_color(border_color)
        .set_align(FormatAlign::Top)
        .set_num_format("hh:mm");

    let headers = [
        "Date",
        "Weekday",
        "Start",
        "End",
        "Type",
        "Course",
        "Class section",
        "Room / Online",
        "Lecturer",
        "Periods",
        "Session",
        "Attendance",
        "Event ID",
    ];

    for (col, text) in headers.iter().enumerate() {
        calendar.write_string_with_format(0, col as u16, *text, &header_fmt)?;
    }

    let weekdays = [
        "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật",
    ];

    let mut row_idx: u32 = 1;
    for ev in &normalized {
        let is_exam = ev.is_exam();
        let rf = if is_exam { &exam_row_fmt } else { &default_row_fmt };
        let df = if is_exam { &exam_date_fmt } else { &date_fmt };
        let tf = if is_exam { &exam_time_fmt } else { &time_fmt };

        let start_dt = ev.start_datetime();
        let end_dt = ev.end_datetime();

        if let Some(s) = start_dt {
            let nd = s.date();
            let date_str = nd.format("%d/%m/%Y").to_string();
            calendar.write_string_with_format(row_idx, 0, &date_str, df)?;

            let weekday_idx = nd.weekday().num_days_from_monday() as usize;
            let wd_str = weekdays.get(weekday_idx).unwrap_or(&"");
            calendar.write_string_with_format(row_idx, 1, *wd_str, rf)?;

            let start_time_str = s.time().format("%H:%M").to_string();
            calendar.write_string_with_format(row_idx, 2, &start_time_str, tf)?;
        } else {
            calendar.write_string_with_format(row_idx, 0, &ev.ngay_hoc, df)?;
            calendar.write_string_with_format(row_idx, 1, "", rf)?;
            calendar.write_string_with_format(row_idx, 2, "", tf)?;
        }

        if let Some(e) = end_dt {
            let end_time_str = e.time().format("%H:%M").to_string();
            calendar.write_string_with_format(row_idx, 3, &end_time_str, tf)?;
        } else {
            calendar.write_string_with_format(row_idx, 3, "", tf)?;
        }

        calendar.write_string_with_format(
            row_idx,
            4,
            if is_exam { "Exam" } else { "Class" },
            rf,
        )?;
        calendar.write_string_with_format(row_idx, 5, ev.course_name(), rf)?;
        calendar.write_string_with_format(row_idx, 6, ev.section_name(), rf)?;
        calendar.write_string_with_format(row_idx, 7, ev.room(), rf)?;
        calendar.write_string_with_format(row_idx, 8, ev.lecturer(), rf)?;
        calendar.write_string_with_format(row_idx, 9, ev.periods_string(), rf)?;
        calendar.write_string_with_format(row_idx, 10, ev.session_desc(), rf)?;
        calendar.write_string_with_format(row_idx, 11, ev.attendance(), rf)?;
        calendar.write_string_with_format(row_idx, 12, ev.id.as_deref().unwrap_or(""), rf)?;

        row_idx += 1;
    }

    calendar.set_freeze_panes(1, 0)?;

    let widths = [
        (0, 13.0),
        (1, 13.0),
        (2, 9.0),
        (3, 9.0),
        (4, 10.0),
        (5, 36.0),
        (6, 44.0),
        (7, 24.0),
        (8, 24.0),
        (9, 10.0),
        (10, 12.0),
        (11, 18.0),
        (12, 34.0),
    ];
    for (col, w) in widths {
        calendar.set_column_width(col, w)?;
    }

    let table = Table::new().set_style(TableStyle::Medium2);
    calendar.add_table(0, 0, row_idx - 1, 12, &table)?;

    // 2. Summary worksheet
    let summary = workbook.add_worksheet();
    summary.set_name("Summary")?;

    let sum_header_fmt = Format::new()
        .set_background_color(navy)
        .set_font_color(Color::RGB(0xFFFFFF))
        .set_bold();

    summary.write_string_with_format(0, 0, "Phenikaa calendar export", &sum_header_fmt)?;
    summary.write_string_with_format(0, 1, "Value", &sum_header_fmt)?;

    let first_dt = normalized.first().and_then(|e| e.start_datetime());
    let last_dt = normalized.last().and_then(|e| e.start_datetime());
    let range_str = match (first_dt, last_dt) {
        (Some(f), Some(l)) => format!("{} – {}", f.format("%d/%m/%Y"), l.format("%d/%m/%Y")),
        _ => String::new(),
    };

    let total_events = normalized.len();
    let class_count = normalized.iter().filter(|e| !e.is_exam()).count();
    let exam_count = normalized.iter().filter(|e| e.is_exam()).count();

    let mut courses_set = HashSet::new();
    let mut course_counts = BTreeMap::new();
    for ev in &normalized {
        let cname = ev.course_name();
        courses_set.insert(cname.clone());
        *course_counts.entry(cname).or_insert(0usize) += 1;
    }

    summary.write_string(1, 0, "Date range")?;
    summary.write_string(1, 1, &range_str)?;

    summary.write_string(2, 0, "Total events")?;
    summary.write_number(2, 1, total_events as f64)?;

    summary.write_string(3, 0, "Classes")?;
    summary.write_number(3, 1, class_count as f64)?;

    summary.write_string(4, 0, "Exams")?;
    summary.write_number(4, 1, exam_count as f64)?;

    summary.write_string(5, 0, "Courses")?;
    summary.write_number(5, 1, courses_set.len() as f64)?;

    summary.write_string_with_format(7, 0, "Course", &sum_header_fmt)?;
    summary.write_string_with_format(7, 1, "Meetings", &sum_header_fmt)?;

    let mut s_row: u32 = 8;
    for (course, count) in course_counts {
        summary.write_string(s_row, 0, &course)?;
        summary.write_number(s_row, 1, count as f64)?;
        s_row += 1;
    }

    summary.set_column_width(0, 48.0)?;
    summary.set_column_width(1, 24.0)?;
    summary.set_freeze_panes(1, 0)?;

    let p = path.as_ref();
    if let Some(parent) = p.parent() {
        std::fs::create_dir_all(parent)?;
    }
    workbook.save(p)?;
    Ok(())
}
