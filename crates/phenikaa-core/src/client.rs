use crate::crypto::{
    xor_b64_decode, xor_b64_encode, BootstrapSession, CALENDAR_ACTION, CALENDAR_ACTION_KEY,
    CALENDAR_API_PATH, PORTAL_BASE_URL, RESPONSE_KEY,
};
use crate::ics::write_ics;
use crate::models::{normalize_events, CalendarEvent, ExportSummary};
use crate::xlsx::write_xlsx;
use chrono::NaiveDate;
use reqwest::header::{
    HeaderMap, HeaderName, HeaderValue, ACCEPT, ACCEPT_LANGUAGE, AUTHORIZATION, CONNECTION,
    CONTENT_TYPE, COOKIE, ORIGIN, REFERER, USER_AGENT,
};
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;
use thiserror::Error;
use tokio::sync::Mutex;

static LAST_REQUEST_TIMESTAMP: AtomicU64 = AtomicU64::new(0);
static RATE_LIMIT_MUTEX: Mutex<()> = Mutex::const_new(());
const MIN_OUTBOUND_INTERVAL_MS: u64 = 1000;

#[derive(Error, Debug)]
pub enum ClientError {
    #[error("start date must not be after end date")]
    InvalidDateRange,
    #[error("session requires userId and tokenJWT")]
    MissingCredentials,
    #[error("crypto error: {0}")]
    Crypto(#[from] crate::crypto::CryptoError),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("http request failed: {0}")]
    Http(#[from] reqwest::Error),
    #[error("Phenikaa session expired; log in again and refresh the authentication source")]
    SessionExpired,
    #[error("Phenikaa API returned HTTP {0}: {1}")]
    HttpStatus(u16, String),
    #[error("Phenikaa API error: {0}")]
    ApiError(String),
    #[error("no calendar events found")]
    NoEventsFound,
    #[error("xlsx error: {0}")]
    Xlsx(#[from] crate::xlsx::XlsxExportError),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
}

pub async fn wait_for_outbound_slot() {
    let _guard = RATE_LIMIT_MUTEX.lock().await;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let last = LAST_REQUEST_TIMESTAMP.load(Ordering::SeqCst);
    if now < last + MIN_OUTBOUND_INTERVAL_MS {
        let sleep_ms = (last + MIN_OUTBOUND_INTERVAL_MS) - now;
        tokio::time::sleep(Duration::from_millis(sleep_ms)).await;
    }
    let after_now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    LAST_REQUEST_TIMESTAMP.store(after_now, Ordering::SeqCst);
}

#[derive(Serialize)]
struct CalendarRequestPayload<'a> {
    action: &'a str,
    func: &'a str,
    #[serde(rename = "iM")]
    im: &'a str,
    #[serde(rename = "strQLSV_NguoiHoc_Id")]
    str_qlsv_nguoi_hoc_id: &'a str,
    #[serde(rename = "strNgayBatDau")]
    str_ngay_bat_dau: String,
    #[serde(rename = "strNgayKetThuc")]
    str_ngay_ket_thuc: String,
    #[serde(rename = "strChucNang_Id")]
    str_chuc_nang_id: &'a str,
    #[serde(rename = "strNguoiThucHien_Id")]
    str_nguoi_thuc_hien_id: &'a str,
}

#[derive(Deserialize)]
struct ApiResponse {
    #[serde(rename = "Success")]
    success: Option<bool>,
    #[serde(rename = "Message")]
    message: Option<String>,
    #[serde(rename = "Data")]
    data: Option<serde_json::Value>,
}

pub async fn fetch_calendar(
    session: &BootstrapSession,
    start: NaiveDate,
    end: NaiveDate,
    base_url: Option<&str>,
    timeout: Option<Duration>,
) -> Result<Vec<CalendarEvent>, ClientError> {
    if start > end {
        return Err(ClientError::InvalidDateRange);
    }
    if session.user_id.is_empty() || session.token_jwt.is_empty() {
        return Err(ClientError::MissingCredentials);
    }

    let payload = CalendarRequestPayload {
        action: CALENDAR_ACTION,
        func: "pkg_congthongtin_hssv_thongtin.LayDSLichCaNhan",
        im: RESPONSE_KEY,
        str_qlsv_nguoi_hoc_id: &session.user_id,
        str_ngay_bat_dau: start.format("%d/%m/%Y").to_string(),
        str_ngay_ket_thuc: end.format("%d/%m/%Y").to_string(),
        str_chuc_nang_id: "",
        str_nguoi_thuc_hien_id: &session.user_id,
    };

    let json_bytes = serde_json::to_vec(&payload)?;
    let json_str = String::from_utf8(json_bytes).unwrap();
    let encrypted = xor_b64_encode(&json_str, CALENDAR_ACTION_KEY)?;

    let base = base_url.unwrap_or(PORTAL_BASE_URL).trim_end_matches('/');
    let target_url = format!("{base}{CALENDAR_API_PATH}");

    let mut headers = HeaderMap::new();
    headers.insert(
        AUTHORIZATION,
        HeaderValue::from_str(&format!("Bearer {}", session.token_jwt))
            .map_err(|_| ClientError::MissingCredentials)?,
    );
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_static("application/x-www-form-urlencoded; charset=UTF-8"),
    );
    headers.insert(
        ACCEPT,
        HeaderValue::from_static("application/json, text/javascript, */*; q=0.01"),
    );
    headers.insert(
        ACCEPT_LANGUAGE,
        HeaderValue::from_static("vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7"),
    );
    headers.insert(
        HeaderName::from_static("x-requested-with"),
        HeaderValue::from_static("XMLHttpRequest"),
    );
    headers.insert(CONNECTION, HeaderValue::from_static("keep-alive"));
    headers.insert(
        USER_AGENT,
        HeaderValue::from_static(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        ),
    );
    headers.insert(ORIGIN, HeaderValue::from_static(PORTAL_BASE_URL));
    headers.insert(
        REFERER,
        HeaderValue::from_static("https://qldtbeta.phenikaa-uni.edu.vn/congsinhvien/index.aspx"),
    );

    if let Some(c) = session.extra.get("cookies").and_then(|v| v.as_str()) {
        if let Ok(val) = HeaderValue::from_str(c) {
            headers.insert(COOKIE, val);
        }
    } else if let Some(ac) = session.extra.get("authCookie").and_then(|v| v.as_str()) {
        if let Ok(val) = HeaderValue::from_str(&format!(".Auth={ac}")) {
            headers.insert(COOKIE, val);
        }
    }

    wait_for_outbound_slot().await;

    let client = reqwest::Client::builder()
        .timeout(timeout.unwrap_or(Duration::from_secs(120)))
        .default_headers(headers)
        .build()?;

    let form_params = [("A", encrypted)];
    let response = client.post(&target_url).form(&form_params).send().await?;

    let status = response.status();
    if status.as_u16() == 401 {
        return Err(ClientError::SessionExpired);
    }
    if !status.is_success() {
        let text = response.text().await.unwrap_or_default();
        return Err(ClientError::HttpStatus(status.as_u16(), text));
    }

    let body_text = response.text().await?;
    let api_res: ApiResponse = serde_json::from_str(&body_text)?;

    if api_res.success != Some(true) {
        return Err(ClientError::ApiError(
            api_res.message.unwrap_or_else(|| "unknown error".into()),
        ));
    }

    let data_val = api_res.data.ok_or_else(|| {
        ClientError::ApiError("Phenikaa API returned an unexpected calendar payload".into())
    })?;

    let events: Vec<CalendarEvent> = if let Some(b_str) = data_val.get("B").and_then(|v| v.as_str())
    {
        let decrypted_json = xor_b64_decode(b_str, RESPONSE_KEY)?;
        serde_json::from_str(&decrypted_json)?
    } else if data_val.is_array() {
        serde_json::from_value(data_val)?
    } else {
        return Err(ClientError::ApiError(
            "Phenikaa API returned an unexpected calendar payload".into(),
        ));
    };

    Ok(normalize_events(events))
}

pub async fn export_calendar_files(
    session: &BootstrapSession,
    start: NaiveDate,
    end: NaiveDate,
    out_dir: &Path,
    prefix: &str,
    calendar_name: &str,
    base_url: Option<&str>,
) -> Result<ExportSummary, ClientError> {
    let events = fetch_calendar(session, start, end, base_url, None).await?;
    if events.is_empty() {
        return Err(ClientError::NoEventsFound);
    }

    std::fs::create_dir_all(out_dir)?;

    let json_path = out_dir.join(format!("{prefix}.json"));
    let xlsx_path = out_dir.join(format!("{prefix}.xlsx"));
    let ics_path = out_dir.join(format!("{prefix}.ics"));

    let json_content = serde_json::to_string_pretty(&events)?;
    std::fs::write(&json_path, json_content.as_bytes())?;

    write_xlsx(&xlsx_path, &events)?;
    write_ics(&ics_path, &events, calendar_name)?;

    let total = events.len();
    let classes = events.iter().filter(|e| !e.is_exam()).count();
    let exams = events.iter().filter(|e| e.is_exam()).count();

    let d_start = events
        .first()
        .and_then(|e| e.start_datetime())
        .map(|dt| dt.date().format("%Y-%m-%d").to_string());
    let d_end = events
        .last()
        .and_then(|e| e.start_datetime())
        .map(|dt| dt.date().format("%Y-%m-%d").to_string());

    Ok(ExportSummary {
        events: total,
        classes,
        exams,
        date_start: d_start,
        date_end: d_end,
        json: Some(json_path.to_string_lossy().to_string()),
        xlsx: Some(xlsx_path.to_string_lossy().to_string()),
        ics: Some(ics_path.to_string_lossy().to_string()),
    })
}
