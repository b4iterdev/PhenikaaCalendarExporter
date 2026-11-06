use chrono::{NaiveDate, NaiveDateTime};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::collections::HashSet;
use std::sync::LazyLock;

static HTML_BREAKS: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)<br\s*/?>").unwrap());

pub fn clean_html_breaks(val: Option<&str>) -> String {
    match val {
        Some(s) => HTML_BREAKS.replace_all(s, "").trim().to_string(),
        None => String::new(),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CalendarEvent {
    #[serde(rename = "ID", default)]
    pub id: Option<String>,
    #[serde(rename = "TENHOCPHAN", default)]
    pub ten_hoc_phan: Option<String>,
    #[serde(rename = "TENLOPHOCPHAN", default)]
    pub ten_lop_hoc_phan: Option<String>,
    #[serde(rename = "DANGKY_LOPHOCPHAN_TEN", default)]
    pub dang_ky_lop_hoc_phan_ten: Option<String>,
    #[serde(rename = "NGAYHOC")]
    pub ngay_hoc: String,
    #[serde(rename = "GIOBATDAU", default)]
    pub gio_bat_dau: Option<f64>,
    #[serde(rename = "PHUTBATDAU", default)]
    pub phut_bat_dau: Option<f64>,
    #[serde(rename = "GIOKETTHUC", default)]
    pub gio_ket_thuc: Option<f64>,
    #[serde(rename = "PHUTKETTHUC", default)]
    pub phut_ket_thuc: Option<f64>,
    #[serde(rename = "TIETBATDAU", default)]
    pub tiet_bat_dau: Option<f64>,
    #[serde(rename = "TIETKETTHUC", default)]
    pub tiet_ket_thuc: Option<f64>,
    #[serde(rename = "TENPHONGHOC", default)]
    pub ten_phong_hoc: Option<String>,
    #[serde(rename = "PHONGHOC_TEN", default)]
    pub phong_hoc_ten: Option<String>,
    #[serde(rename = "GIANGVIEN", default)]
    pub giang_vien: Option<String>,
    #[serde(rename = "PHANLOAI", default)]
    pub phan_loai: Option<String>,
    #[serde(rename = "BUOIHOC", default)]
    pub buoi_hoc: Option<String>,
    #[serde(rename = "THONGTINCHUYENCAN", default)]
    pub thong_tin_chuyen_can: Option<String>,

    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, serde_json::Value>,
}

impl CalendarEvent {
    pub fn is_exam(&self) -> bool {
        self.phan_loai.as_deref() == Some("LICHTHI")
    }

    pub fn course_name(&self) -> String {
        clean_html_breaks(self.ten_hoc_phan.as_deref())
    }

    pub fn section_name(&self) -> String {
        let sec = self
            .ten_lop_hoc_phan
            .as_deref()
            .or(self.dang_ky_lop_hoc_phan_ten.as_deref());
        clean_html_breaks(sec)
    }

    pub fn room(&self) -> String {
        let rm = self
            .ten_phong_hoc
            .as_deref()
            .or(self.phong_hoc_ten.as_deref());
        clean_html_breaks(rm)
    }

    pub fn lecturer(&self) -> String {
        clean_html_breaks(self.giang_vien.as_deref())
    }

    pub fn session_desc(&self) -> String {
        clean_html_breaks(self.buoi_hoc.as_deref())
    }

    pub fn attendance(&self) -> String {
        clean_html_breaks(self.thong_tin_chuyen_can.as_deref())
    }

    pub fn parse_date(&self) -> Option<NaiveDate> {
        NaiveDate::parse_from_str(self.ngay_hoc.trim(), "%d/%m/%Y").ok()
    }

    pub fn start_datetime(&self) -> Option<NaiveDateTime> {
        let d = self.parse_date()?;
        let hour = self.gio_bat_dau.unwrap_or(0.0) as u32;
        let minute = self.phut_bat_dau.unwrap_or(0.0) as u32;
        d.and_hms_opt(hour, minute, 0)
    }

    pub fn end_datetime(&self) -> Option<NaiveDateTime> {
        let d = self.parse_date()?;
        let hour = self.gio_ket_thuc.unwrap_or(0.0) as u32;
        let minute = self.phut_ket_thuc.unwrap_or(0.0) as u32;
        d.and_hms_opt(hour, minute, 0)
    }

    pub fn periods_string(&self) -> String {
        match (self.tiet_bat_dau, self.tiet_ket_thuc) {
            (Some(s), Some(e)) => format!("{}-{}", s as i64, e as i64),
            _ => String::new(),
        }
    }
}

pub fn normalize_events(events: Vec<CalendarEvent>) -> Vec<CalendarEvent> {
    let mut output: Vec<CalendarEvent> = Vec::with_capacity(events.len());
    let mut seen = HashSet::new();

    for mut event in events {
        if let Some(ref sec) = event.ten_lop_hoc_phan {
            event.ten_lop_hoc_phan = Some(clean_html_breaks(Some(sec)));
        }
        let identity = (
            event.id.clone().unwrap_or_default(),
            event.ngay_hoc.clone(),
            event.gio_bat_dau.map(|v| v.to_bits()),
            event.phut_bat_dau.map(|v| v.to_bits()),
            event.ten_hoc_phan.clone().unwrap_or_default(),
            event.ten_lop_hoc_phan.clone().unwrap_or_default(),
        );
        if seen.insert(identity) {
            output.push(event);
        }
    }

    output.sort_by(|a, b| {
        let dt_a = a.start_datetime();
        let dt_b = b.start_datetime();
        dt_a.cmp(&dt_b).then_with(|| {
            a.course_name().cmp(&b.course_name())
        })
    });

    output
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportSummary {
    pub events: usize,
    pub classes: usize,
    pub exams: usize,
    pub date_start: Option<String>,
    pub date_end: Option<String>,
    pub json: Option<String>,
    pub xlsx: Option<String>,
    pub ics: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_events_dedup_and_sort() {
        let raw = r#"[
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
            },
            {
                "ID": "class-1",
                "TENHOCPHAN": "Học máy nâng cao",
                "TENLOPHOCPHAN": "Học máy nâng cao(N01)<br><br>",
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
            }
        ]"#;

        let events: Vec<CalendarEvent> = serde_json::from_str(raw).unwrap();
        let normalized = normalize_events(events);
        assert_eq!(normalized.len(), 2);
        assert_eq!(normalized[0].id.as_deref(), Some("class-1"));
        assert_eq!(normalized[1].id.as_deref(), Some("exam-1"));
        assert_eq!(normalized[0].section_name(), "Học máy nâng cao(N01)");
    }
}
