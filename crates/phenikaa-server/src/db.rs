use chrono::Utc;
use serde::{Deserialize, Serialize};
use sqlx::{sqlite::SqlitePoolOptions, sqlite::SqliteRow, FromRow, Pool, Row, Sqlite};
use std::path::Path;
use thiserror::Error;

pub const STATUS_PENDING_LOGIN: &str = "pending_login";
pub const STATUS_ACTIVE: &str = "active";
pub const STATUS_NEEDS_HUMAN: &str = "needs_human";
pub const STATUS_DISABLED: &str = "disabled";

pub const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    oidc_sub TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_login',
    phenikaa_user_id TEXT,
    token_encrypted TEXT,
    token_fingerprint TEXT,
    range_start TEXT,
    range_end TEXT,
    sync_interval_hours REAL,
    last_sync_at TEXT,
    last_sync_status TEXT,
    last_sync_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_user_grants (
    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    google_sub TEXT UNIQUE NOT NULL,
    email TEXT NOT NULL,
    credentials_encrypted TEXT NOT NULL,
    sync_enabled INTEGER NOT NULL DEFAULT 1,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    refreshed_token INTEGER NOT NULL DEFAULT 0,
    events INTEGER,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS google_connections (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    access_token_encrypted TEXT NOT NULL,
    refresh_token_encrypted TEXT NOT NULL,
    token_type TEXT NOT NULL DEFAULT 'Bearer',
    scope TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL,
    calendar_id TEXT,
    migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS google_calendar_state (
    session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
    calendar_id TEXT,
    migration_state TEXT NOT NULL DEFAULT 'app_calendar_ready',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_event_links (
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    calendar_id TEXT NOT NULL DEFAULT 'primary',
    source_key TEXT NOT NULL,
    google_event_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, calendar_id, source_key)
);
CREATE TABLE IF NOT EXISTS api_tokens (
    id TEXT PRIMARY KEY,
    owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    token_prefix TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    scopes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_owner_created_at
    ON api_tokens(owner_user_id, created_at);
"#;

#[derive(Error, Debug)]
pub enum DbError {
    #[error("sqlx error: {0}")]
    Sqlx(#[from] sqlx::Error),
    #[error("user not found")]
    UserNotFound,
    #[error("session not found")]
    SessionNotFound,
    #[error("user already has a session")]
    OwnerSessionExists,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct User {
    pub id: i64,
    pub oidc_sub: String,
    pub display_name: String,
    pub created_at: String,
}

impl<'r> FromRow<'r, SqliteRow> for User {
    fn from_row(row: &'r SqliteRow) -> Result<Self, sqlx::Error> {
        Ok(Self {
            id: row.try_get("id")?,
            oidc_sub: row.try_get("oidc_sub")?,
            display_name: row.try_get("display_name")?,
            created_at: row.try_get("created_at")?,
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Session {
    pub id: String,
    pub owner_user_id: i64,
    pub label: String,
    pub status: String,
    pub phenikaa_user_id: Option<String>,
    pub token_encrypted: Option<String>,
    pub token_fingerprint: Option<String>,
    pub range_start: Option<String>,
    pub range_end: Option<String>,
    pub sync_interval_hours: Option<f64>,
    pub last_sync_at: Option<String>,
    pub last_sync_status: Option<String>,
    pub last_sync_error: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

impl<'r> FromRow<'r, SqliteRow> for Session {
    fn from_row(row: &'r SqliteRow) -> Result<Self, sqlx::Error> {
        Ok(Self {
            id: row.try_get("id")?,
            owner_user_id: row.try_get("owner_user_id")?,
            label: row.try_get("label")?,
            status: row.try_get("status")?,
            phenikaa_user_id: row.try_get("phenikaa_user_id")?,
            token_encrypted: row.try_get("token_encrypted")?,
            token_fingerprint: row.try_get("token_fingerprint")?,
            range_start: row.try_get("range_start")?,
            range_end: row.try_get("range_end")?,
            sync_interval_hours: row.try_get("sync_interval_hours")?,
            last_sync_at: row.try_get("last_sync_at")?,
            last_sync_status: row.try_get("last_sync_status")?,
            last_sync_error: row.try_get("last_sync_error")?,
            created_at: row.try_get("created_at")?,
            updated_at: row.try_get("updated_at")?,
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SyncRun {
    pub id: i64,
    pub session_id: String,
    pub started_at: String,
    pub finished_at: Option<String>,
    pub ok: i64,
    pub refreshed_token: i64,
    pub events: Option<i64>,
    pub detail: Option<String>,
}

impl<'r> FromRow<'r, SqliteRow> for SyncRun {
    fn from_row(row: &'r SqliteRow) -> Result<Self, sqlx::Error> {
        Ok(Self {
            id: row.try_get("id")?,
            session_id: row.try_get("session_id")?,
            started_at: row.try_get("started_at")?,
            finished_at: row.try_get("finished_at")?,
            ok: row.try_get("ok")?,
            refreshed_token: row.try_get("refreshed_token")?,
            events: row.try_get("events")?,
            detail: row.try_get("detail")?,
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GoogleConnection {
    pub session_id: String,
    pub access_token_encrypted: String,
    pub refresh_token_encrypted: String,
    pub token_type: String,
    pub scope: String,
    pub expires_at: String,
    pub calendar_id: Option<String>,
    pub migration_state: String,
    pub connected_at: String,
    pub updated_at: String,
    pub last_error: Option<String>,
}

impl<'r> FromRow<'r, SqliteRow> for GoogleConnection {
    fn from_row(row: &'r SqliteRow) -> Result<Self, sqlx::Error> {
        Ok(Self {
            session_id: row.try_get("session_id")?,
            access_token_encrypted: row.try_get("access_token_encrypted")?,
            refresh_token_encrypted: row.try_get("refresh_token_encrypted")?,
            token_type: row.try_get("token_type")?,
            scope: row.try_get("scope")?,
            expires_at: row.try_get("expires_at")?,
            calendar_id: row.try_get("calendar_id")?,
            migration_state: row.try_get("migration_state")?,
            connected_at: row.try_get("connected_at")?,
            updated_at: row.try_get("updated_at")?,
            last_error: row.try_get("last_error")?,
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GoogleEventLink {
    pub session_id: String,
    pub calendar_id: String,
    pub source_key: String,
    pub google_event_id: String,
    pub updated_at: String,
}

impl<'r> FromRow<'r, SqliteRow> for GoogleEventLink {
    fn from_row(row: &'r SqliteRow) -> Result<Self, sqlx::Error> {
        Ok(Self {
            session_id: row.try_get("session_id")?,
            calendar_id: row.try_get("calendar_id")?,
            source_key: row.try_get("source_key")?,
            google_event_id: row.try_get("google_event_id")?,
            updated_at: row.try_get("updated_at")?,
        })
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ApiToken {
    pub id: String,
    pub owner_user_id: i64,
    pub token_hash: String,
    pub token_prefix: String,
    pub name: String,
    pub scopes: String,
    pub created_at: String,
    pub last_used_at: Option<String>,
    pub revoked_at: Option<String>,
}

impl<'r> FromRow<'r, SqliteRow> for ApiToken {
    fn from_row(row: &'r SqliteRow) -> Result<Self, sqlx::Error> {
        Ok(Self {
            id: row.try_get("id")?,
            owner_user_id: row.try_get("owner_user_id")?,
            token_hash: row.try_get("token_hash")?,
            token_prefix: row.try_get("token_prefix")?,
            name: row.try_get("name")?,
            scopes: row.try_get("scopes")?,
            created_at: row.try_get("created_at")?,
            last_used_at: row.try_get("last_used_at")?,
            revoked_at: row.try_get("revoked_at")?,
        })
    }
}

#[derive(Clone)]
pub struct Database {
    pool: Pool<Sqlite>,
}

#[derive(Clone, Debug, Default)]
pub struct NewSyncRun<'a> {
    pub session_id: &'a str,
    pub started_at: &'a str,
    pub finished_at: Option<&'a str>,
    pub ok: bool,
    pub refreshed_token: bool,
    pub events: Option<i64>,
    pub detail: Option<&'a str>,
}

impl Database {
    pub async fn connect<P: AsRef<Path>>(path: P) -> Result<Self, DbError> {
        let p = path.as_ref();
        if let Some(parent) = p.parent() {
            tokio::fs::create_dir_all(parent).await.ok();
        }
        let url = format!("sqlite://{}?mode=rwc", p.display());
        let pool = SqlitePoolOptions::new()
            .max_connections(5)
            .connect(&url)
            .await?;

        sqlx::query("PRAGMA foreign_keys = ON;")
            .execute(&pool)
            .await?;

        for stmt in SCHEMA.split(';') {
            let trimmed = stmt.trim();
            if !trimmed.is_empty() {
                sqlx::query(trimmed).execute(&pool).await?;
            }
        }

        Ok(Self { pool })
    }

    pub fn pool(&self) -> &Pool<Sqlite> {
        &self.pool
    }

    pub async fn get_or_create_user(
        &self,
        oidc_sub: &str,
        display_name: &str,
    ) -> Result<User, DbError> {
        let existing = sqlx::query_as::<_, User>("SELECT * FROM users WHERE oidc_sub = ?")
            .bind(oidc_sub)
            .fetch_optional(&self.pool)
            .await?;

        if let Some(user) = existing {
            return Ok(user);
        }

        let now = Utc::now().to_rfc3339();
        let res = sqlx::query(
            "INSERT INTO users (oidc_sub, display_name, created_at) VALUES (?, ?, ?)",
        )
        .bind(oidc_sub)
        .bind(display_name)
        .bind(&now)
        .execute(&self.pool)
        .await?;

        Ok(User {
            id: res.last_insert_rowid(),
            oidc_sub: oidc_sub.to_string(),
            display_name: display_name.to_string(),
            created_at: now,
        })
    }

    pub async fn get_session_by_id(&self, id: &str) -> Result<Option<Session>, DbError> {
        let sess = sqlx::query_as::<_, Session>("SELECT * FROM sessions WHERE id = ?")
            .bind(id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(sess)
    }

    pub async fn get_session_by_owner(&self, owner_id: i64) -> Result<Option<Session>, DbError> {
        let sess = sqlx::query_as::<_, Session>("SELECT * FROM sessions WHERE owner_user_id = ?")
            .bind(owner_id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(sess)
    }

    pub async fn create_session(
        &self,
        id: &str,
        owner_id: i64,
        label: &str,
        range_start: Option<&str>,
        range_end: Option<&str>,
        sync_interval_hours: f64,
    ) -> Result<Session, DbError> {
        if self.get_session_by_owner(owner_id).await?.is_some() {
            return Err(DbError::OwnerSessionExists);
        }

        let now = Utc::now().to_rfc3339();
        sqlx::query(
            r#"INSERT INTO sessions (
                id, owner_user_id, label, status, range_start, range_end,
                sync_interval_hours, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"#,
        )
        .bind(id)
        .bind(owner_id)
        .bind(label)
        .bind(STATUS_PENDING_LOGIN)
        .bind(range_start)
        .bind(range_end)
        .bind(sync_interval_hours)
        .bind(&now)
        .bind(&now)
        .execute(&self.pool)
        .await?;

        self.get_session_by_id(id)
            .await?
            .ok_or(DbError::SessionNotFound)
    }

    pub async fn update_session_credentials(
        &self,
        session_id: &str,
        phenikaa_user_id: &str,
        token_encrypted: &str,
        token_fingerprint: &str,
    ) -> Result<(), DbError> {
        let now = Utc::now().to_rfc3339();
        sqlx::query(
            r#"UPDATE sessions SET
                phenikaa_user_id = ?,
                token_encrypted = ?,
                token_fingerprint = ?,
                status = ?,
                updated_at = ?
            WHERE id = ?"#,
        )
        .bind(phenikaa_user_id)
        .bind(token_encrypted)
        .bind(token_fingerprint)
        .bind(STATUS_ACTIVE)
        .bind(&now)
        .bind(session_id)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn list_due_sessions(&self) -> Result<Vec<Session>, DbError> {
        let rows = sqlx::query_as::<_, Session>(
            "SELECT * FROM sessions WHERE status = ? AND token_encrypted IS NOT NULL",
        )
        .bind(STATUS_ACTIVE)
        .fetch_all(&self.pool)
        .await?;
        Ok(rows)
    }

    pub async fn record_sync_run(
        &self,
        run: &NewSyncRun<'_>,
    ) -> Result<i64, DbError> {
        let res = sqlx::query(
            r#"INSERT INTO sync_runs (
                session_id, started_at, finished_at, ok, refreshed_token, events, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?)"#,
        )
        .bind(run.session_id)
        .bind(run.started_at)
        .bind(run.finished_at)
        .bind(if run.ok { 1 } else { 0 })
        .bind(if run.refreshed_token { 1 } else { 0 })
        .bind(run.events)
        .bind(run.detail)
        .execute(&self.pool)
        .await?;
        Ok(res.last_insert_rowid())
    }

    pub async fn get_sync_runs(&self, session_id: &str, limit: i64) -> Result<Vec<SyncRun>, DbError> {
        let rows = sqlx::query_as::<_, SyncRun>(
            "SELECT * FROM sync_runs WHERE session_id = ? ORDER BY started_at DESC LIMIT ?",
        )
        .bind(session_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await?;
        Ok(rows)
    }

    pub async fn get_google_connection(&self, session_id: &str) -> Result<Option<GoogleConnection>, DbError> {
        let conn = sqlx::query_as::<_, GoogleConnection>(
            "SELECT * FROM google_connections WHERE session_id = ?",
        )
        .bind(session_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(conn)
    }

    pub async fn upsert_google_connection(
        &self,
        session_id: &str,
        access_token_encrypted: &str,
        refresh_token_encrypted: &str,
        token_type: &str,
        scope: &str,
        expires_at: &str,
    ) -> Result<(), DbError> {
        let now = Utc::now().to_rfc3339();
        sqlx::query(
            r#"INSERT INTO google_connections (
                session_id, access_token_encrypted, refresh_token_encrypted,
                token_type, scope, expires_at, connected_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                access_token_encrypted = excluded.access_token_encrypted,
                refresh_token_encrypted = excluded.refresh_token_encrypted,
                token_type = excluded.token_type,
                scope = excluded.scope,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at"#,
        )
        .bind(session_id)
        .bind(access_token_encrypted)
        .bind(refresh_token_encrypted)
        .bind(token_type)
        .bind(scope)
        .bind(expires_at)
        .bind(&now)
        .bind(&now)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn delete_google_connection(&self, session_id: &str) -> Result<(), DbError> {
        sqlx::query("DELETE FROM google_connections WHERE session_id = ?")
            .bind(session_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn set_google_connection_error(&self, session_id: &str, error: Option<&str>) -> Result<(), DbError> {
        let now = Utc::now().to_rfc3339();
        sqlx::query("UPDATE google_connections SET last_error = ?, updated_at = ? WHERE session_id = ?")
            .bind(error)
            .bind(&now)
            .bind(session_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn set_google_calendar_id(&self, session_id: &str, calendar_id: &str) -> Result<(), DbError> {
        let now = Utc::now().to_rfc3339();
        sqlx::query("UPDATE google_connections SET calendar_id = ?, updated_at = ? WHERE session_id = ?")
            .bind(calendar_id)
            .bind(&now)
            .bind(session_id)
            .execute(&self.pool)
            .await?;
        Ok(())
    }

    pub async fn list_google_event_links(
        &self,
        session_id: &str,
        calendar_id: &str,
    ) -> Result<Vec<GoogleEventLink>, DbError> {
        let rows = sqlx::query_as::<_, GoogleEventLink>(
            "SELECT * FROM google_event_links WHERE session_id = ? AND calendar_id = ?",
        )
        .bind(session_id)
        .bind(calendar_id)
        .fetch_all(&self.pool)
        .await?;
        Ok(rows)
    }

    pub async fn upsert_google_event_link(
        &self,
        session_id: &str,
        source_key: &str,
        google_event_id: &str,
        calendar_id: &str,
    ) -> Result<(), DbError> {
        let now = Utc::now().to_rfc3339();
        sqlx::query(
            r#"INSERT INTO google_event_links (
                session_id, calendar_id, source_key, google_event_id, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, calendar_id, source_key) DO UPDATE SET
                google_event_id = excluded.google_event_id,
                updated_at = excluded.updated_at"#,
        )
        .bind(session_id)
        .bind(calendar_id)
        .bind(source_key)
        .bind(google_event_id)
        .bind(&now)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn delete_google_event_link(
        &self,
        session_id: &str,
        source_key: &str,
        calendar_id: &str,
    ) -> Result<(), DbError> {
        sqlx::query(
            "DELETE FROM google_event_links WHERE session_id = ? AND calendar_id = ? AND source_key = ?",
        )
        .bind(session_id)
        .bind(calendar_id)
        .bind(source_key)
        .execute(&self.pool)
        .await?;
        Ok(())
    }

    pub async fn delete_google_event_links_for_calendar(
        &self,
        session_id: &str,
        calendar_id: &str,
    ) -> Result<(), DbError> {
        sqlx::query(
            "DELETE FROM google_event_links WHERE session_id = ? AND calendar_id = ?",
        )
        .bind(session_id)
        .bind(calendar_id)
        .execute(&self.pool)
        .await?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_db_lifecycle() {
        let temp = tempfile::tempdir().unwrap();
        let db_path = temp.path().join("test.db");
        let db = Database::connect(&db_path).await.unwrap();

        let user = db.get_or_create_user("sub-1", "Test User").await.unwrap();
        assert_eq!(user.oidc_sub, "sub-1");

        let session = db
            .create_session("sess-1", user.id, "My Calendar", None, None, 24.0)
            .await
            .unwrap();
        assert_eq!(session.status, STATUS_PENDING_LOGIN);

        db.update_session_credentials("sess-1", "std-1", "enc-tok", "fp-1")
            .await
            .unwrap();
        let updated = db.get_session_by_id("sess-1").await.unwrap().unwrap();
        assert_eq!(updated.status, STATUS_ACTIVE);
        assert_eq!(updated.phenikaa_user_id.as_deref(), Some("std-1"));

        db.record_sync_run(&NewSyncRun {
            session_id: "sess-1",
            started_at: "2026-08-01T00:00:00Z",
            finished_at: None,
            ok: true,
            refreshed_token: false,
            events: Some(15),
            detail: None,
        })
        .await
        .unwrap();
        let runs = db.get_sync_runs("sess-1", 10).await.unwrap();
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].events, Some(15));
    }
}
