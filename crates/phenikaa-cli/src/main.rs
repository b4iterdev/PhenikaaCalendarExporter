use chrono::NaiveDate;
use clap::Parser;
use phenikaa_core::{
    default_cache_dir, export_calendar_files, extract_auth_from_cache, parse_bootstrap_html,
    BootstrapSession, PORTAL_BASE_URL,
};
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

#[derive(Parser, Debug)]
#[command(
    name = "phenikaa-calendar",
    about = "Export an authenticated Phenikaa learning calendar to XLSX, ICS, and JSON"
)]
struct Args {
    /// Inclusive start date, YYYY-MM-DD
    #[arg(long, value_parser = parse_date)]
    start: NaiveDate,

    /// Inclusive end date, YYYY-MM-DD
    #[arg(long, value_parser = parse_date)]
    end: NaiveDate,

    /// Private JSON containing userId and tokenJWT
    #[arg(long)]
    auth_json: Option<PathBuf>,

    /// Authenticated saved index.aspx HTML containing AXYZCLRVN
    #[arg(long)]
    bootstrap_html: Option<PathBuf>,

    /// Chromium Cache_Data directory containing the authenticated index page
    #[arg(long)]
    cache_dir: Option<PathBuf>,

    /// Output directory
    #[arg(long, default_value = "exports")]
    out_dir: PathBuf,

    /// Output filename prefix
    #[arg(long, default_value = "phenikaa_calendar")]
    prefix: String,

    /// ICS calendar display name
    #[arg(long, default_value = "Phenikaa Learning Calendar")]
    calendar_name: String,

    /// Portal base URL
    #[arg(long, default_value = PORTAL_BASE_URL)]
    base_url: String,
}

fn parse_date(s: &str) -> Result<NaiveDate, String> {
    NaiveDate::parse_from_str(s, "%Y-%m-%d").map_err(|e| format!("dates must use YYYY-MM-DD: {e}"))
}

fn load_session(args: &Args) -> Result<BootstrapSession, Box<dyn std::error::Error>> {
    if let Some(ref path) = args.auth_json {
        let content = fs::read_to_string(path)?;
        let session: BootstrapSession = serde_json::from_str(&content)?;
        if session.user_id.is_empty() || session.token_jwt.is_empty() {
            return Err("authentication JSON is missing userId or tokenJWT".into());
        }
        return Ok(session);
    }

    if let Some(ref path) = args.bootstrap_html {
        let content = fs::read_to_string(path)?;
        let session = parse_bootstrap_html(&content)?;
        return Ok(session);
    }

    if let Some(ref dir) = args.cache_dir {
        let session = extract_auth_from_cache(dir)?;
        return Ok(session);
    }

    if let Some(def_dir) = default_cache_dir() {
        if let Ok(session) = extract_auth_from_cache(&def_dir) {
            return Ok(session);
        }
    }

    Err("no credentials provided and none found in Chromium cache. Provide --auth-json, --bootstrap-html, or --cache-dir".into())
}

#[tokio::main]
async fn main() -> ExitCode {
    let args = Args::parse();

    if args.start > args.end {
        eprintln!("Error: start date must not be after end date");
        return ExitCode::from(1);
    }

    let session = match load_session(&args) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("Error loading credentials: {e}");
            return ExitCode::from(1);
        }
    };

    match export_calendar_files(
        &session,
        args.start,
        args.end,
        &args.out_dir,
        &args.prefix,
        &args.calendar_name,
        Some(&args.base_url),
    )
    .await
    {
        Ok(summary) => {
            let json = serde_json::to_string_pretty(&summary).unwrap();
            println!("{json}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("Export error: {e}");
            ExitCode::from(1)
        }
    }
}
