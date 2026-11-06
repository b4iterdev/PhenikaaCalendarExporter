use crate::db::Database;
use crate::sync::SyncEngine;
use axum::{
    extract::{Path, State},
    http::StatusCode,
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState {
    pub database: Database,
    pub sync_engine: Arc<SyncEngine>,
    pub google_service: Option<crate::google::GoogleCalendarService>,
}

#[derive(Serialize)]
pub struct ApiResponse<T: Serialize> {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<T>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ApiErrorDetail>,
}

#[derive(Serialize)]
pub struct ApiErrorDetail {
    pub code: String,
    pub message: String,
}

pub fn ok_resp<T: Serialize>(data: T) -> (StatusCode, Json<ApiResponse<T>>) {
    (
        StatusCode::OK,
        Json(ApiResponse {
            ok: true,
            data: Some(data),
            error: None,
        }),
    )
}

pub fn err_resp(status: StatusCode, code: &str, msg: &str) -> (StatusCode, Json<ApiResponse<()>>) {
    (
        status,
        Json(ApiResponse {
            ok: false,
            data: None,
            error: Some(ApiErrorDetail {
                code: code.to_string(),
                message: msg.to_string(),
            }),
        }),
    )
}

#[derive(Deserialize)]
pub struct CreateSessionRequest {
    pub id: String,
    pub owner_id: i64,
    #[serde(default)]
    pub label: String,
    #[serde(default)]
    pub range_start: Option<String>,
    #[serde(default)]
    pub range_end: Option<String>,
    #[serde(default = "default_sync_interval")]
    pub sync_interval_hours: f64,
}

fn default_sync_interval() -> f64 {
    24.0
}

pub async fn health_handler() -> impl IntoResponse {
    let payload = serde_json::json!({
        "status": "ok",
        "service": "phenikaa-calendar-server",
        "version": "1.0.0"
    });
    ok_resp(payload)
}

pub async fn list_sessions_handler(State(state): State<AppState>) -> impl IntoResponse {
    match state.database.list_due_sessions().await {
        Ok(sessions) => ok_resp(serde_json::json!(sessions)).into_response(),
        Err(e) => err_resp(StatusCode::INTERNAL_SERVER_ERROR, "db_error", &e.to_string()).into_response(),
    }
}

pub async fn create_session_handler(
    State(state): State<AppState>,
    Json(payload): Json<CreateSessionRequest>,
) -> impl IntoResponse {
    if payload.id.is_empty()
        || payload.id.contains('/')
        || payload.id.contains('\\')
        || payload.id.contains("..")
    {
        return err_resp(StatusCode::BAD_REQUEST, "invalid_id", "invalid session id").into_response();
    }
    match state
        .database
        .create_session(
            &payload.id,
            payload.owner_id,
            &payload.label,
            payload.range_start.as_deref(),
            payload.range_end.as_deref(),
            payload.sync_interval_hours,
        )
        .await
    {
        Ok(session) => ok_resp(serde_json::json!(session)).into_response(),
        Err(crate::db::DbError::OwnerSessionExists) => err_resp(
            StatusCode::CONFLICT,
            "session_exists",
            "user already has an active session",
        )
        .into_response(),
        Err(e) => err_resp(StatusCode::INTERNAL_SERVER_ERROR, "db_error", &e.to_string()).into_response(),
    }
}

pub async fn get_session_handler(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match state.database.get_session_by_id(&id).await {
        Ok(Some(sess)) => ok_resp(serde_json::json!(sess)).into_response(),
        Ok(None) => err_resp(StatusCode::NOT_FOUND, "not_found", "session not found").into_response(),
        Err(e) => err_resp(StatusCode::INTERNAL_SERVER_ERROR, "db_error", &e.to_string()).into_response(),
    }
}

pub async fn trigger_sync_handler(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match state.database.get_session_by_id(&id).await {
        Ok(Some(sess)) => {
            state.sync_engine.request_sync(&sess.id).await;
            ok_resp(serde_json::json!({
                "message": "sync requested",
                "session_id": sess.id
            }))
            .into_response()
        }
        Ok(None) => err_resp(StatusCode::NOT_FOUND, "not_found", "session not found").into_response(),
        Err(e) => err_resp(StatusCode::INTERNAL_SERVER_ERROR, "db_error", &e.to_string()).into_response(),
    }
}

pub async fn get_sync_runs_handler(
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> impl IntoResponse {
    match state.database.get_sync_runs(&id, 20).await {
        Ok(runs) => ok_resp(serde_json::json!(runs)).into_response(),
        Err(e) => err_resp(StatusCode::INTERNAL_SERVER_ERROR, "db_error", &e.to_string()).into_response(),
    }
}

#[derive(Deserialize)]
pub struct GoogleAuthUrlQuery {
    pub session_id: String,
}

#[derive(Deserialize)]
pub struct GoogleCallbackQuery {
    pub code: String,
    pub state: String,
}

pub async fn google_auth_url_handler(
    State(state): State<AppState>,
    axum::extract::Query(query): axum::extract::Query<GoogleAuthUrlQuery>,
) -> impl IntoResponse {
    match &state.google_service {
        Some(gsync) => {
            let url = crate::google::authorization_url(&gsync.config, &query.session_id);
            ok_resp(serde_json::json!({ "url": url })).into_response()
        }
        None => err_resp(
            StatusCode::BAD_REQUEST,
            "not_configured",
            "Google OAuth is not configured on this server",
        )
        .into_response(),
    }
}

pub async fn google_callback_handler(
    State(state): State<AppState>,
    axum::extract::Query(query): axum::extract::Query<GoogleCallbackQuery>,
) -> impl IntoResponse {
    match &state.google_service {
        Some(gsync) => {
            // state is session_id
            match gsync.exchange_code(&query.state, &query.code).await {
                Ok(_) => {
                    // Trigger initial sync
                    state.sync_engine.request_sync(&query.state).await;
                    ok_resp(serde_json::json!({
                        "message": "Google Calendar connected successfully",
                        "session_id": query.state
                    }))
                    .into_response()
                }
                Err(e) => err_resp(
                    StatusCode::INTERNAL_SERVER_ERROR,
                    "oauth_exchange_failed",
                    &e.to_string(),
                )
                .into_response(),
            }
        }
        None => err_resp(
            StatusCode::BAD_REQUEST,
            "not_configured",
            "Google OAuth is not configured on this server",
        )
        .into_response(),
    }
}

pub fn api_router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(health_handler))
        .route("/sessions", get(list_sessions_handler).post(create_session_handler))
        .route("/sessions/{id}", get(get_session_handler))
        .route("/sessions/{id}/sync", post(trigger_sync_handler))
        .route("/sessions/{id}/sync_runs", get(get_sync_runs_handler))
        .route("/google/auth_url", get(google_auth_url_handler))
        .route("/google/callback", get(google_callback_handler))
        .with_state(state)
}
