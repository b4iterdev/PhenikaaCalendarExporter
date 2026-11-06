use chrono::NaiveDate;
use httpmock::prelude::*;
use phenikaa_core::{
    export_calendar_files, fetch_calendar, write_xlsx, BootstrapSession, CalendarEvent,
    CALENDAR_ACTION, RESPONSE_KEY,
};
use tempfile::tempdir;

const SAMPLE_JSON: &str = r#"[
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

#[tokio::test]
async fn test_fetch_and_export_calendar() {
    let server = MockServer::start();
    let enc_events = phenikaa_core::xor_b64_encode(SAMPLE_JSON, RESPONSE_KEY).unwrap();
    let response_body = serde_json::json!({
        "Success": true,
        "Data": {
            "B": enc_events
        }
    });

    let mock = server.mock(|when, then| {
        when.method(POST)
            .path_contains(CALENDAR_ACTION)
            .header("Authorization", "Bearer secret-token");
        then.status(200)
            .header("Content-Type", "application/json")
            .json_body(response_body);
    });

    let session = BootstrapSession {
        user_id: "student-id".into(),
        token_jwt: "secret-token".into(),
        root_path: None,
        extra: Default::default(),
    };

    let start = NaiveDate::from_ymd_opt(2026, 8, 1).unwrap();
    let end = NaiveDate::from_ymd_opt(2026, 10, 31).unwrap();

    let events = fetch_calendar(&session, start, end, Some(&server.base_url()), None)
        .await
        .unwrap();

    mock.assert();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0].id.as_deref(), Some("class-1"));
    assert_eq!(events[1].id.as_deref(), Some("exam-1"));

    let out = tempdir().unwrap();
    let summary = export_calendar_files(
        &session,
        start,
        end,
        out.path(),
        "semester",
        "Semester Calendar",
        Some(&server.base_url()),
    )
    .await
    .unwrap();

    assert_eq!(summary.events, 2);
    assert_eq!(summary.classes, 1);
    assert_eq!(summary.exams, 1);
    assert_eq!(summary.date_start.as_deref(), Some("2026-08-24"));
    assert_eq!(summary.date_end.as_deref(), Some("2026-10-28"));

    assert!(out.path().join("semester.json").exists());
    assert!(out.path().join("semester.xlsx").exists());
    assert!(out.path().join("semester.ics").exists());
}

#[test]
fn test_xlsx_export() {
    let events: Vec<CalendarEvent> = serde_json::from_str(SAMPLE_JSON).unwrap();
    let out = tempdir().unwrap();
    let xlsx_file = out.path().join("calendar.xlsx");

    write_xlsx(&xlsx_file, &events).unwrap();
    assert!(xlsx_file.exists());
    assert!(xlsx_file.metadata().unwrap().len() > 1000);
}
