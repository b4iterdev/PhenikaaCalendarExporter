use axum::{
    body::Body,
    http::{Request, StatusCode},
};
use http_body_util::BodyExt;
use phenikaa_server::{
    create_app, Database, ServerConfig, SyncEngine, TokenVault,
};
use std::sync::Arc;
use tempfile::tempdir;
use tower::ServiceExt;

#[tokio::test]
async fn test_health_and_session_routes() {
    let temp = tempdir().unwrap();
    let mut config = ServerConfig::default();
    config.state_dir = temp.path().to_path_buf();
    config.ensure_dirs().unwrap();

    let vault = TokenVault::new(&fernet::Fernet::generate_key()).unwrap();
    let database = Database::connect(config.db_path()).await.unwrap();
    let sync_engine = Arc::new(SyncEngine::new(config.clone(), database.clone(), vault, None));

    let app = create_app(config, database, sync_engine, None);

    // 1. Health check
    let req = Request::builder()
        .uri("/api/v1/health")
        .body(Body::empty())
        .unwrap();
    let res = app.clone().oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);

    let body = res.into_body().collect().await.unwrap().to_bytes();
    let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
    assert_eq!(json["ok"], true);
    assert_eq!(json["data"]["status"], "ok");

    // 2. Landing page
    let req = Request::builder().uri("/").body(Body::empty()).unwrap();
    let res = app.clone().oneshot(req).await.unwrap();
    assert_eq!(res.status(), StatusCode::OK);
}
