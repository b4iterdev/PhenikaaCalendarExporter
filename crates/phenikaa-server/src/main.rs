use phenikaa_server::config::ServerConfig;
use phenikaa_server::crypto::{load_or_create_key, TokenVault};
use phenikaa_server::db::Database;
use phenikaa_server::sync::SyncEngine;
use phenikaa_server::web::create_app;
use std::net::SocketAddr;
use std::sync::Arc;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info,phenikaa_server=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = ServerConfig::from_env();
    config.ensure_dirs()?;

    let key = if !config.encryption_key.is_empty() {
        config.encryption_key.clone()
    } else {
        load_or_create_key(config.key_path())?
    };

    let vault = TokenVault::new(&key)?;
    let database = Database::connect(config.db_path()).await?;

    let google_service = if config.google_oauth_configured() {
        Some(phenikaa_server::GoogleCalendarService::new(
            phenikaa_server::GoogleOAuthConfig {
                client_id: config.google_client_id.clone(),
                client_secret: config.google_client_secret.clone(),
                redirect_uri: config.google_redirect_uri.clone(),
            },
            database.clone(),
            vault.clone(),
        ))
    } else {
        None
    };

    let sync_engine = Arc::new(SyncEngine::new(
        config.clone(),
        database.clone(),
        vault,
        google_service.clone(),
    ));

    sync_engine.clone().start_worker();

    let app = create_app(config.clone(), database, sync_engine, google_service);

    let addr: SocketAddr = format!("{}:{}", config.host, config.port).parse()?;
    tracing::info!("Phenikaa calendar server listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
