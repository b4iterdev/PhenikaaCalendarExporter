use crate::crypto::TokenVault;
use crate::db::{Database, GoogleConnection};
use chrono::{DateTime, Duration, Utc};
use phenikaa_core::crypto::TIMEZONE;
use phenikaa_core::models::{clean_html_breaks, normalize_events, CalendarEvent};
use serde::Serialize;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use thiserror::Error;

pub const AUTH_URL: &str = "https://accounts.google.com/o/oauth2/v2/auth";
pub const TOKEN_URL: &str = "https://oauth2.googleapis.com/token";
pub const REVOKE_URL: &str = "https://oauth2.googleapis.com/revoke";
pub const CALENDARS_URL: &str = "https://www.googleapis.com/calendar/v3/calendars";
pub const APP_CALENDAR_SUMMARY: &str = "Phenikaa Learning Calendar";
pub const APP_CREATED_SCOPE: &str = "https://www.googleapis.com/auth/calendar.app.created";
pub const APP_PRIVATE_KEY: &str = "phenikaaCalendarSourceKey";

#[derive(Error, Debug)]
pub enum GoogleError {
    #[error("google calendar error: {0}")]
    Api(String),
    #[error("db error: {0}")]
    Db(#[from] crate::db::DbError),
    #[error("crypto error: {0}")]
    Crypto(#[from] crate::crypto::CryptoError),
    #[error("http error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Debug)]
pub struct GoogleOAuthConfig {
    pub client_id: String,
    pub client_secret: String,
    pub redirect_uri: String,
}

#[derive(Clone, Debug, Default, Serialize)]
pub struct GoogleSyncResult {
    pub attempted: bool,
    pub ok: bool,
    pub created: usize,
    pub updated: usize,
    pub deleted: usize,
    pub detail: String,
}

pub fn authorization_url(config: &GoogleOAuthConfig, state: &str) -> String {
    let mut url = reqwest::Url::parse(AUTH_URL).unwrap();
    url.query_pairs_mut()
        .append_pair("client_id", &config.client_id)
        .append_pair("redirect_uri", &config.redirect_uri)
        .append_pair("response_type", "code")
        .append_pair("scope", APP_CREATED_SCOPE)
        .append_pair("state", state)
        .append_pair("access_type", "offline")
        .append_pair("prompt", "consent");
    url.to_string()
}

pub fn source_key(event: &CalendarEvent) -> String {
    let id_str = clean_html_breaks(event.id.as_deref());
    let ngay_hoc = event.ngay_hoc.clone();
    let gio_bat_dau = event.gio_bat_dau.map(|v| v.to_string()).unwrap_or_default();
    let phut_bat_dau = event.phut_bat_dau.map(|v| v.to_string()).unwrap_or_default();
    let ten_hoc_phan = clean_html_breaks(event.ten_hoc_phan.as_deref());
    let mut section = clean_html_breaks(event.ten_lop_hoc_phan.as_deref());
    if section.is_empty() {
        section = clean_html_breaks(event.dang_ky_lop_hoc_phan_ten.as_deref());
    }
    let gio_ket_thuc = event.gio_ket_thuc.map(|v| v.to_string()).unwrap_or_default();
    let phut_ket_thuc = event.phut_ket_thuc.map(|v| v.to_string()).unwrap_or_default();

    let tuple = (
        &id_str,
        &ngay_hoc,
        &gio_bat_dau,
        &phut_bat_dau,
        &ten_hoc_phan,
        &section,
        &gio_ket_thuc,
        &phut_ket_thuc,
    );

    let json_bytes = serde_json::to_vec(&tuple).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(&json_bytes);
    let digest = format!("{:x}", hasher.finalize());

    if id_str.is_empty() {
        format!("phenikaa:derived:{digest}")
    } else {
        format!("phenikaa:id:{digest}")
    }
}

pub fn google_event_body(event: &CalendarEvent) -> serde_json::Value {
    let is_exam = event.is_exam();
    let cname = event.course_name();
    let summary = if is_exam {
        format!("Exam: {cname}")
    } else {
        cname
    };

    let start_dt = event
        .start_datetime()
        .map(|d| d.format("%Y-%m-%dT%H:%M:%S").to_string())
        .unwrap_or_default();
    let end_dt = event
        .end_datetime()
        .map(|d| d.format("%Y-%m-%dT%H:%M:%S").to_string())
        .unwrap_or_default();

    let section = event.section_name();
    let lecturer = event.lecturer();
    let periods = event.periods_string();
    let attendance = event.attendance();

    let mut desc_lines = Vec::new();
    if !section.is_empty() {
        desc_lines.push(format!("Class: {section}"));
    }
    if !lecturer.is_empty() {
        desc_lines.push(format!("Lecturer: {lecturer}"));
    }
    if !periods.is_empty() {
        desc_lines.push(format!("Periods: {periods}"));
    }
    if !attendance.is_empty() {
        desc_lines.push(format!("Attendance: {attendance}"));
    }

    serde_json::json!({
        "summary": summary,
        "location": event.room(),
        "description": desc_lines.join("\n"),
        "start": {
            "dateTime": start_dt,
            "timeZone": TIMEZONE
        },
        "end": {
            "dateTime": end_dt,
            "timeZone": TIMEZONE
        }
    })
}

#[derive(Clone)]
pub struct GoogleCalendarService {
    pub config: GoogleOAuthConfig,
    pub database: Database,
    pub vault: TokenVault,
    pub client: reqwest::Client,
    pub calendars_base_url: String,
}

impl GoogleCalendarService {
    pub fn new(config: GoogleOAuthConfig, database: Database, vault: TokenVault) -> Self {
        Self {
            config,
            database,
            vault,
            client: reqwest::Client::new(),
            calendars_base_url: CALENDARS_URL.to_string(),
        }
    }

    pub fn with_calendars_url(mut self, url: String) -> Self {
        self.calendars_base_url = url;
        self
    }

    pub async fn exchange_code(&self, session_id: &str, code: &str) -> Result<(), GoogleError> {
        let params = [
            ("code", code),
            ("client_id", &self.config.client_id),
            ("client_secret", &self.config.client_secret),
            ("redirect_uri", &self.config.redirect_uri),
            ("grant_type", "authorization_code"),
        ];

        let res = self
            .client
            .post(TOKEN_URL)
            .form(&params)
            .send()
            .await?;

        if !res.status().is_success() {
            let body = res.text().await.unwrap_or_default();
            return Err(GoogleError::Api(format!("token exchange failed: {body}")));
        }

        let token_data: serde_json::Value = res.json().await?;
        let access_token = token_data["access_token"]
            .as_str()
            .ok_or_else(|| GoogleError::Api("missing access_token".into()))?;
        let refresh_token = token_data["refresh_token"].as_str().unwrap_or("");
        let expires_in = token_data["expires_in"].as_i64().unwrap_or(3600);
        let expires_at = (Utc::now() + Duration::seconds(expires_in)).to_rfc3339();

        let access_enc = self.vault.encrypt(access_token);
        let refresh_enc = self.vault.encrypt(refresh_token);

        self.database
            .upsert_google_connection(
                session_id,
                &access_enc,
                &refresh_enc,
                "Bearer",
                APP_CREATED_SCOPE,
                &expires_at,
            )
            .await?;

        Ok(())
    }

    pub async fn get_valid_access_token(
        &self,
        session_id: &str,
        conn: &GoogleConnection,
    ) -> Result<String, GoogleError> {
        let expires_at = DateTime::parse_from_rfc3339(&conn.expires_at)
            .map(|dt| dt.with_timezone(&Utc))
            .unwrap_or_else(|_| Utc::now());

        if expires_at - Utc::now() > Duration::seconds(60) {
            return Ok(self.vault.decrypt(&conn.access_token_encrypted)?);
        }

        // Refresh token
        let refresh_token = self.vault.decrypt(&conn.refresh_token_encrypted)?;
        let params: [(&str, &str); 4] = [
            ("client_id", self.config.client_id.as_str()),
            ("client_secret", self.config.client_secret.as_str()),
            ("refresh_token", refresh_token.as_str()),
            ("grant_type", "refresh_token"),
        ];

        let res = self
            .client
            .post(TOKEN_URL)
            .form(&params)
            .send()
            .await?;

        if !res.status().is_success() {
            let body = res.text().await.unwrap_or_default();
            return Err(GoogleError::Api(format!("token refresh failed: {body}")));
        }

        let token_data: serde_json::Value = res.json().await?;
        let new_access = token_data["access_token"]
            .as_str()
            .ok_or_else(|| GoogleError::Api("missing access_token".into()))?;
        let expires_in = token_data["expires_in"].as_i64().unwrap_or(3600);
        let expires_at = (Utc::now() + Duration::seconds(expires_in)).to_rfc3339();

        let access_enc = self.vault.encrypt(new_access);
        self.database
            .upsert_google_connection(
                session_id,
                &access_enc,
                &conn.refresh_token_encrypted,
                "Bearer",
                &conn.scope,
                &expires_at,
            )
            .await?;

        Ok(new_access.to_string())
    }

    pub async fn ensure_app_calendar(
        &self,
        session_id: &str,
        access_token: &str,
        conn: &GoogleConnection,
    ) -> Result<String, GoogleError> {
        if let Some(ref cal_id) = conn.calendar_id {
            if !cal_id.is_empty() && cal_id != "primary" {
                let check_url = format!("{}/{}", self.calendars_base_url, cal_id);
                let res = self
                    .client
                    .get(&check_url)
                    .bearer_auth(access_token)
                    .send()
                    .await?;
                if res.status().is_success() {
                    return Ok(cal_id.clone());
                }
            }
        }

        // Create new dedicated calendar
        let res = self
            .client
            .post(&self.calendars_base_url)
            .bearer_auth(access_token)
            .json(&serde_json::json!({
                "summary": APP_CALENDAR_SUMMARY
            }))
            .send()
            .await?;

        if !res.status().is_success() {
            let body = res.text().await.unwrap_or_default();
            return Err(GoogleError::Api(format!("failed to create calendar: {body}")));
        }

        let cal: serde_json::Value = res.json().await?;
        let new_id = cal["id"]
            .as_str()
            .ok_or_else(|| GoogleError::Api("missing calendar id in response".into()))?;

        self.database.set_google_calendar_id(session_id, new_id).await?;
        Ok(new_id.to_string())
    }

    pub async fn sync_events(
        &self,
        session_id: &str,
        events: &[CalendarEvent],
    ) -> Result<GoogleSyncResult, GoogleError> {
        let conn = match self.database.get_google_connection(session_id).await? {
            Some(c) => c,
            None => {
                return Ok(GoogleSyncResult {
                    attempted: false,
                    ok: true,
                    detail: "Google Calendar is not connected".into(),
                    ..Default::default()
                })
            }
        };

        let access_token = match self.get_valid_access_token(session_id, &conn).await {
            Ok(tok) => tok,
            Err(e) => {
                let err_msg = format!("auth error: {e}");
                self.database
                    .set_google_connection_error(session_id, Some(&err_msg))
                    .await?;
                return Err(e);
            }
        };

        let calendar_id = self.ensure_app_calendar(session_id, &access_token, &conn).await?;

        let normalized = normalize_events(events.to_vec());
        let mut desired = HashMap::new();
        for ev in &normalized {
            let key = source_key(ev);
            let mut body = google_event_body(ev);
            body["extendedProperties"] = serde_json::json!({
                "private": {
                    APP_PRIVATE_KEY: key
                }
            });
            desired.insert(key, body);
        }

        let links = self.database.list_google_event_links(session_id, &calendar_id).await?;
        let links_map: HashMap<String, String> = links
            .into_iter()
            .map(|l| (l.source_key, l.google_event_id))
            .collect();

        let mut created = 0;
        let mut updated = 0;
        let mut deleted = 0;

        let events_url = format!("{}/{}/events", self.calendars_base_url, calendar_id);

        for (key, body) in &desired {
            if let Some(event_id) = links_map.get(key) {
                let event_url = format!("{events_url}/{event_id}");
                let res = self
                    .client
                    .put(&event_url)
                    .bearer_auth(&access_token)
                    .json(body)
                    .send()
                    .await?;

                if res.status().is_success() {
                    updated += 1;
                } else if res.status().as_u16() == 404 {
                    // Re-insert
                    let post_res = self
                        .client
                        .post(&events_url)
                        .bearer_auth(&access_token)
                        .json(body)
                        .send()
                        .await?;
                    if post_res.status().is_success() {
                        let inserted: serde_json::Value = post_res.json().await?;
                        if let Some(new_id) = inserted["id"].as_str() {
                            self.database
                                .upsert_google_event_link(session_id, key, new_id, &calendar_id)
                                .await?;
                            created += 1;
                        }
                    }
                }
            } else {
                let post_res = self
                    .client
                    .post(&events_url)
                    .bearer_auth(&access_token)
                    .json(body)
                    .send()
                    .await?;
                if post_res.status().is_success() {
                    let inserted: serde_json::Value = post_res.json().await?;
                    if let Some(new_id) = inserted["id"].as_str() {
                        self.database
                            .upsert_google_event_link(session_id, key, new_id, &calendar_id)
                            .await?;
                        created += 1;
                    }
                }
            }
        }

        // Clean up deletions
        for (key, event_id) in &links_map {
            if !desired.contains_key(key) {
                let event_url = format!("{events_url}/{event_id}");
                let _ = self
                    .client
                    .delete(&event_url)
                    .bearer_auth(&access_token)
                    .send()
                    .await;
                self.database
                    .delete_google_event_link(session_id, key, &calendar_id)
                    .await?;
                deleted += 1;
            }
        }

        self.database.set_google_connection_error(session_id, None).await?;

        let detail = format!(
            "Google Calendar sync created {created}, updated {updated}, deleted {deleted}"
        );

        Ok(GoogleSyncResult {
            attempted: true,
            ok: true,
            created,
            updated,
            deleted,
            detail,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_source_key_generation() {
        let raw = r#"{
            "ID": "class-1",
            "TENHOCPHAN": "Học máy nâng cao",
            "TENLOPHOCPHAN": "Học máy nâng cao(N01)",
            "NGAYHOC": "24/08/2026",
            "GIOBATDAU": 6.0,
            "PHUTBATDAU": 45.0,
            "GIOKETTHUC": 9.0,
            "PHUTKETTHUC": 25.0
        }"#;
        let event: CalendarEvent = serde_json::from_str(raw).unwrap();
        let key = source_key(&event);
        assert!(key.starts_with("phenikaa:id:"));
        assert_eq!(key.len(), 12 + 64);
    }
}
