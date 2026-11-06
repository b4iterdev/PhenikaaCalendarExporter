use crate::config::{academic_year_range, ServerConfig};
use crate::crypto::TokenVault;
use crate::db::{Database, Session};
use crate::google::GoogleCalendarService;
use chrono::{DateTime, NaiveDate, Utc};
use phenikaa_core::{fetch_calendar, write_ics, BootstrapSession, CalendarEvent};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;
use thiserror::Error;
use tokio::sync::{Mutex, Notify};

#[derive(Error, Debug)]
pub enum SyncError {
    #[error("db error: {0}")]
    Db(#[from] crate::db::DbError),
    #[error("crypto error: {0}")]
    Crypto(#[from] crate::crypto::CryptoError),
    #[error("core client error: {0}")]
    Client(#[from] phenikaa_core::ClientError),
    #[error("session needs human interaction: {0}")]
    NeedsHuman(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
}

#[derive(Clone, Debug)]
pub struct SyncResult {
    pub ok: bool,
    pub events: usize,
    pub refreshed: bool,
    pub detail: String,
}

#[derive(Clone)]
pub struct SyncEngine {
    config: ServerConfig,
    database: Database,
    vault: TokenVault,
    google_service: Option<GoogleCalendarService>,
    wake_notify: Arc<Notify>,
    forced_queue: Arc<Mutex<Vec<String>>>,
}

impl SyncEngine {
    pub fn new(
        config: ServerConfig,
        database: Database,
        vault: TokenVault,
        google_service: Option<GoogleCalendarService>,
    ) -> Self {
        Self {
            config,
            database,
            vault,
            google_service,
            wake_notify: Arc::new(Notify::new()),
            forced_queue: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub async fn request_sync(&self, session_id: &str) {
        let mut queue = self.forced_queue.lock().await;
        if !queue.contains(&session_id.to_string()) {
            queue.push(session_id.to_string());
        }
        self.wake_notify.notify_one();
    }

    pub fn start_worker(self: Arc<Self>) -> tokio::task::JoinHandle<()> {
        tokio::spawn(async move {
            let mut interval = tokio::time::interval(Duration::from_secs(60));
            loop {
                tokio::select! {
                    _ = interval.tick() => {
                        self.sync_due().await;
                    }
                    _ = self.wake_notify.notified() => {
                        self.sync_due().await;
                    }
                }
            }
        })
    }

    pub async fn sync_due(&self) -> Vec<SyncResult> {
        let forced = {
            let mut q = self.forced_queue.lock().await;
            let list = q.clone();
            q.clear();
            list
        };

        let sessions = match self.database.list_due_sessions().await {
            Ok(s) => s,
            Err(e) => {
                tracing::error!("failed to list due sessions: {e}");
                return Vec::new();
            }
        };

        let now = Utc::now();
        let mut results = Vec::new();

        for session in sessions {
            let is_forced = forced.contains(&session.id);
            let interval_hours = session
                .sync_interval_hours
                .unwrap_or(self.config.sync_interval_hours);

            let is_due = match &session.last_sync_at {
                None => true,
                Some(ts) => match DateTime::parse_from_rfc3339(ts) {
                    Ok(parsed) => {
                        now.signed_duration_since(parsed.with_timezone(&Utc))
                            >= chrono::Duration::seconds((interval_hours * 3600.0) as i64)
                    }
                    Err(_) => true,
                },
            };

            if is_forced || is_due {
                let res = self.sync_session(&session).await;
                results.push(res);
            }
        }

        results
    }

    pub async fn sync_session(&self, session: &Session) -> SyncResult {
        let started_at = Utc::now().to_rfc3339();
        let _run_id = match self
            .database
            .record_sync_run(&session.id, &started_at, None, false, false, None, None)
            .await
        {
            Ok(id) => id,
            Err(e) => {
                return SyncResult {
                    ok: false,
                    events: 0,
                    refreshed: false,
                    detail: format!("db error recording run: {e}"),
                };
            }
        };

        match self.do_sync_session(session).await {
            Ok((events, refreshed, detail)) => {
                let finished_at = Utc::now().to_rfc3339();
                let _ = self
                    .database
                    .record_sync_run(
                        &session.id,
                        &started_at,
                        Some(&finished_at),
                        true,
                        refreshed,
                        Some(events.len() as i64),
                        Some(&detail),
                    )
                    .await;
                SyncResult {
                    ok: true,
                    events: events.len(),
                    refreshed,
                    detail,
                }
            }
            Err(e) => {
                let finished_at = Utc::now().to_rfc3339();
                let detail = e.to_string();
                let _ = self
                    .database
                    .record_sync_run(
                        &session.id,
                        &started_at,
                        Some(&finished_at),
                        false,
                        false,
                        None,
                        Some(&detail),
                    )
                    .await;
                SyncResult {
                    ok: false,
                    events: 0,
                    refreshed: false,
                    detail,
                }
            }
        }
    }

    async fn do_sync_session(
        &self,
        session: &Session,
    ) -> Result<(Vec<CalendarEvent>, bool, String), SyncError> {
        let encrypted = session
            .token_encrypted
            .as_deref()
            .ok_or_else(|| SyncError::NeedsHuman("session requires interactive login".into()))?;
        let user_id = session
            .phenikaa_user_id
            .as_deref()
            .ok_or_else(|| SyncError::NeedsHuman("missing phenikaa_user_id".into()))?;

        let decrypted = self.vault.decrypt(encrypted)?;
        let (token_jwt, auth_cookie) = if decrypted.starts_with('{') && decrypted.contains("tokenJWT") {
            let val: serde_json::Value = serde_json::from_str(&decrypted)?;
            let tok = val["tokenJWT"].as_str().unwrap_or("").to_string();
            let cookie = val.get("authCookie").and_then(|c| c.as_str()).map(String::from);
            (tok, cookie)
        } else {
            (decrypted, None)
        };

        let mut extra = HashMap::new();
        if let Some(cookie) = auth_cookie {
            extra.insert("authCookie".to_string(), serde_json::Value::String(cookie));
        }

        let bootstrap = BootstrapSession {
            user_id: user_id.to_string(),
            token_jwt,
            root_path: None,
            extra,
        };

        let (default_start, default_end) = academic_year_range(None);
        let start = match &session.range_start {
            Some(s) => NaiveDate::parse_from_str(s, "%Y-%m-%d").unwrap_or(default_start),
            None => default_start,
        };
        let end = match &session.range_end {
            Some(e) => NaiveDate::parse_from_str(e, "%Y-%m-%d").unwrap_or(default_end),
            None => default_end,
        };

        let events = fetch_calendar(&bootstrap, start, end, None, None).await?;

        // Write outputs atomically
        let session_export_dir = self.config.exports_dir().join(&session.id);
        tokio::fs::create_dir_all(&session_export_dir).await?;

        let json_tmp = session_export_dir.join("calendar.json.tmp");
        let json_target = session_export_dir.join("calendar.json");
        let json_bytes = serde_json::to_string_pretty(&events)?;
        tokio::fs::write(&json_tmp, json_bytes.as_bytes()).await?;
        tokio::fs::rename(&json_tmp, &json_target).await?;

        let ics_tmp = session_export_dir.join("calendar.ics.tmp");
        let ics_target = session_export_dir.join("calendar.ics");
        write_ics(&ics_tmp, &events, "Phenikaa Learning Calendar")?;
        tokio::fs::rename(&ics_tmp, &ics_target).await?;

        let mut detail = format!("saved {} events", events.len());

        if let Some(ref gsync) = self.google_service {
            match gsync.sync_events(&session.id, &events).await {
                Ok(gres) if gres.attempted => {
                    detail.push_str("; ");
                    detail.push_str(&gres.detail);
                }
                Err(ge) => {
                    detail.push_str(&format!("; Google sync error: {ge}"));
                }
                _ => {}
            }
        }

        Ok((events, false, detail))
    }
}
