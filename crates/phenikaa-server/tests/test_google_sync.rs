use httpmock::prelude::*;
use phenikaa_core::models::CalendarEvent;
use phenikaa_server::crypto::TokenVault;
use phenikaa_server::db::Database;
use phenikaa_server::google::{
    GoogleCalendarService, GoogleOAuthConfig, APP_CALENDAR_SUMMARY,
};
use tempfile::tempdir;

#[tokio::test]
async fn test_google_sync_creates_events_and_links() {
    let mock_server = MockServer::start();

    // 1. Mock create calendar
    let mock_cal = mock_server.mock(|when, then| {
        when.method(POST)
            .path("/calendars")
            .header("Authorization", "Bearer valid-access-tok");
        then.status(200)
            .header("Content-Type", "application/json")
            .json_body(serde_json::json!({
                "id": "new-cal-id",
                "summary": APP_CALENDAR_SUMMARY
            }));
    });

    // 2. Mock create event
    let mock_evt = mock_server.mock(|when, then| {
        when.method(POST)
            .path("/calendars/new-cal-id/events")
            .header("Authorization", "Bearer valid-access-tok");
        then.status(200)
            .header("Content-Type", "application/json")
            .json_body(serde_json::json!({
                "id": "g-event-123"
            }));
    });

    let temp = tempdir().unwrap();
    let db = Database::connect(temp.path().join("test.db")).await.unwrap();
    let key = fernet::Fernet::generate_key();
    let vault = TokenVault::new(&key).unwrap();

    let user = db.get_or_create_user("sub-1", "Test User").await.unwrap();
    let _session = db
        .create_session("test-session", user.id, "My Calendar", None, None, 24.0)
        .await
        .unwrap();

    let session_id = "test-session";
    let expires_at = (chrono::Utc::now() + chrono::Duration::hours(2)).to_rfc3339();

    db.upsert_google_connection(
        session_id,
        &vault.encrypt("valid-access-tok"),
        &vault.encrypt("refresh-tok"),
        "Bearer",
        "https://www.googleapis.com/auth/calendar.app.created",
        &expires_at,
    )
    .await
    .unwrap();

    let config = GoogleOAuthConfig {
        client_id: "test-client".into(),
        client_secret: "test-secret".into(),
        redirect_uri: "http://localhost/callback".into(),
    };

    let google = GoogleCalendarService::new(config, db.clone(), vault)
        .with_calendars_url(format!("{}/calendars", mock_server.base_url()));

    let sample_raw = r#"[
        {
            "ID": "class-1",
            "TENHOCPHAN": "Học máy nâng cao",
            "TENLOPHOCPHAN": "Học máy nâng cao(N01)",
            "NGAYHOC": "24/08/2026",
            "GIOBATDAU": 6.0,
            "PHUTBATDAU": 45.0,
            "GIOKETTHUC": 9.0,
            "PHUTKETTHUC": 25.0
        }
    ]"#;
    let events: Vec<CalendarEvent> = serde_json::from_str(sample_raw).unwrap();

    let res = google.sync_events(session_id, &events).await.unwrap();
    assert!(res.attempted);
    assert!(res.ok);
    assert_eq!(res.created, 1);
    assert_eq!(res.updated, 0);

    mock_cal.assert();
    mock_evt.assert();

    let links = db.list_google_event_links(session_id, "new-cal-id").await.unwrap();
    assert_eq!(links.len(), 1);
    assert_eq!(links[0].google_event_id, "g-event-123");
}
