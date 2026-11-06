use crate::api_v1::{api_router, AppState};
use crate::config::ServerConfig;
use crate::db::Database;
use crate::sync::SyncEngine;
use axum::{
    body::Body,
    extract::Path,
    http::{header, HeaderValue, StatusCode},
    response::{Html, IntoResponse, Response},
    routing::get,
    Router,
};
use std::sync::Arc;
use tower_http::cors::CorsLayer;
use tower_http::services::ServeDir;

const LANDING_PAGE_HTML: &str = r#"<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Phenikaa Calendar Exporter</title>
    <link rel="stylesheet" href="/static/styles.css">
</head>
<body class="bg-gray-50 text-gray-900 font-sans antialiased min-h-screen flex flex-col items-center justify-center p-4">
    <div class="max-w-xl w-full bg-white rounded-xl shadow-md border border-gray-100 p-8">
        <h1 class="text-2xl font-bold text-gray-900 mb-2">Phenikaa Calendar Exporter</h1>
        <p class="text-gray-600 mb-6 text-sm">
            Tự động đồng bộ lịch học và lịch thi từ cổng sinh viên Phenikaa sang Google Calendar, Apple Calendar, và Outlook.
        </p>
        <div class="border-t border-gray-100 pt-6 space-y-4">
            <div class="flex items-center justify-between text-sm">
                <span class="text-gray-500">Service Status</span>
                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                    Online (Rust Core)
                </span>
            </div>
            <div class="flex items-center justify-between text-sm">
                <span class="text-gray-500">API Documentation</span>
                <a href="/api/v1/health" class="text-blue-600 hover:text-blue-800 font-medium">/api/v1/health</a>
            </div>
        </div>
    </div>
</body>
</html>
"#;

pub async fn root_handler() -> Html<&'static str> {
    Html(LANDING_PAGE_HTML)
}

pub async fn download_export(
    Path((session_id, filename)): Path<(String, String)>,
    config: ServerConfig,
) -> impl IntoResponse {
    let allowed = ["calendar.ics", "calendar.json", "calendar.xlsx"];
    if !allowed.contains(&filename.as_str()) {
        return (StatusCode::NOT_FOUND, "Not found").into_response();
    }

    let file_path = config.exports_dir().join(&session_id).join(&filename);
    if !file_path.exists() {
        return (StatusCode::NOT_FOUND, "Export file not found").into_response();
    }

    match tokio::fs::read(&file_path).await {
        Ok(bytes) => {
            let mime = if filename.ends_with(".ics") {
                "text/calendar; charset=utf-8"
            } else if filename.ends_with(".json") {
                "application/json"
            } else {
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            };

            Response::builder()
                .status(StatusCode::OK)
                .header(header::CONTENT_TYPE, HeaderValue::from_static(mime))
                .body(Body::from(bytes))
                .unwrap()
        }
        Err(_) => (StatusCode::INTERNAL_SERVER_ERROR, "Failed to read export").into_response(),
    }
}

pub fn create_app(
    config: ServerConfig,
    database: Database,
    sync_engine: Arc<SyncEngine>,
    google_service: Option<crate::google::GoogleCalendarService>,
) -> Router {
    let app_state = AppState {
        database,
        sync_engine,
        google_service,
    };

    let static_dir = std::env::current_dir()
        .map(|p| p.join("server/static"))
        .unwrap_or_else(|_| "server/static".into());

    let conf = config.clone();

    Router::new()
        .route("/", get(root_handler))
        .route(
            "/exports/{session_id}/{filename}",
            get(move |p| download_export(p, conf.clone())),
        )
        .nest("/api/v1", api_router(app_state))
        .nest_service("/static", ServeDir::new(static_dir))
        .layer(CorsLayer::permissive())
}
