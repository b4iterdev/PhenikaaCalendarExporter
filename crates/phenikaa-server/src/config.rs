use chrono::{Datelike, NaiveDate};
use std::collections::HashSet;
use std::env;
use std::path::PathBuf;

pub const DEFAULT_STATE_DIR: &str = "server-state";
pub const DEFAULT_HOST: &str = "127.0.0.1";
pub const DEFAULT_PORT: u16 = 8416;
pub const DEFAULT_SYNC_INTERVAL_HOURS: f64 = 24.0;
pub const DEFAULT_RANGE_START_MONTH: u32 = 8;
pub const DEFAULT_RANGE_START_DAY: u32 = 1;

pub fn academic_year_range(today: Option<NaiveDate>) -> (NaiveDate, NaiveDate) {
    let now = today.unwrap_or_else(|| chrono::Local::now().date_naive());
    let mut start = NaiveDate::from_ymd_opt(now.year(), DEFAULT_RANGE_START_MONTH, DEFAULT_RANGE_START_DAY).unwrap();
    if now < start {
        start = NaiveDate::from_ymd_opt(now.year() - 1, DEFAULT_RANGE_START_MONTH, DEFAULT_RANGE_START_DAY).unwrap();
    }
    let end = NaiveDate::from_ymd_opt(start.year() + 1, 7, 31).unwrap();
    (start, end)
}

#[derive(Clone, Debug)]
pub struct ServerConfig {
    pub state_dir: PathBuf,
    pub host: String,
    pub port: u16,
    pub base_url: String,
    pub sync_interval_hours: f64,
    pub encryption_key: String,
    pub auth_mode: String,
    pub oidc_issuer: String,
    pub oidc_client_id: String,
    pub oidc_client_secret: String,
    pub oidc_redirect_uri: String,
    pub google_client_id: String,
    pub google_client_secret: String,
    pub google_redirect_uri: String,
    pub trusted_proxies: HashSet<String>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self::from_env()
    }
}

impl ServerConfig {
    pub fn from_env() -> Self {
        let state_dir = PathBuf::from(
            env::var("PHENIKAA_SERVER_STATE").unwrap_or_else(|_| DEFAULT_STATE_DIR.to_string()),
        );
        let host = env::var("PHENIKAA_SERVER_HOST").unwrap_or_else(|_| DEFAULT_HOST.to_string());
        let port = env::var("PHENIKAA_SERVER_PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(DEFAULT_PORT);
        let base_url = env::var("PHENIKAA_SERVER_BASE_URL").unwrap_or_default();
        let sync_interval_hours = env::var("PHENIKAA_SERVER_SYNC_INTERVAL_HOURS")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(DEFAULT_SYNC_INTERVAL_HOURS);
        let encryption_key = env::var("PHENIKAA_SERVER_KEY").unwrap_or_default();
        let auth_mode = env::var("PHENIKAA_SERVER_AUTH").unwrap_or_else(|_| "oidc".to_string());
        let oidc_issuer = env::var("PHENIKAA_OIDC_ISSUER").unwrap_or_default();
        let oidc_client_id = env::var("PHENIKAA_OIDC_CLIENT_ID").unwrap_or_default();
        let oidc_client_secret = env::var("PHENIKAA_OIDC_CLIENT_SECRET").unwrap_or_default();
        let oidc_redirect_uri = env::var("PHENIKAA_OIDC_REDIRECT_URI").unwrap_or_default();
        let google_client_id = env::var("PHENIKAA_GOOGLE_CLIENT_ID").unwrap_or_default();
        let google_client_secret = env::var("PHENIKAA_GOOGLE_CLIENT_SECRET").unwrap_or_default();
        let google_redirect_uri = env::var("PHENIKAA_GOOGLE_REDIRECT_URI").unwrap_or_default();

        let proxies_raw = env::var("PHENIKAA_SERVER_TRUSTED_PROXIES")
            .unwrap_or_else(|_| "127.0.0.1,::1".to_string());
        let trusted_proxies = proxies_raw
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        Self {
            state_dir,
            host,
            port,
            base_url,
            sync_interval_hours,
            encryption_key,
            auth_mode,
            oidc_issuer,
            oidc_client_id,
            oidc_client_secret,
            oidc_redirect_uri,
            google_client_id,
            google_client_secret,
            google_redirect_uri,
            trusted_proxies,
        }
    }

    pub fn db_path(&self) -> PathBuf {
        self.state_dir.join("server.db")
    }

    pub fn key_path(&self) -> PathBuf {
        self.state_dir.join("secret.key")
    }

    pub fn exports_dir(&self) -> PathBuf {
        self.state_dir.join("exports")
    }

    pub fn ensure_dirs(&self) -> std::io::Result<()> {
        std::fs::create_dir_all(&self.state_dir)?;
        std::fs::create_dir_all(self.exports_dir())?;
        Ok(())
    }

    pub fn google_oauth_configured(&self) -> bool {
        !self.google_client_id.is_empty()
            && !self.google_client_secret.is_empty()
            && !self.google_redirect_uri.is_empty()
    }
}
