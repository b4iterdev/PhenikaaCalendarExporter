pub mod cache;
pub mod client;
pub mod crypto;
pub mod ics;
pub mod models;
pub mod xlsx;

pub use cache::{default_cache_dir, extract_auth_from_cache};
pub use client::{export_calendar_files, fetch_calendar, wait_for_outbound_slot, ClientError};
pub use crypto::{
    decode_bootstrap_blob, parse_bootstrap_html, xor_b64_decode, xor_b64_encode, BootstrapSession,
    CryptoError, BOOTSTRAP_KEY, CALENDAR_ACTION, CALENDAR_ACTION_KEY, CALENDAR_API_PATH,
    PORTAL_BASE_URL, RESPONSE_KEY, TIMEZONE,
};
pub use ics::{generate_ics, write_ics};
pub use models::{clean_html_breaks, normalize_events, CalendarEvent, ExportSummary};
pub use xlsx::write_xlsx;
