use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::LazyLock;
use thiserror::Error;

pub const BOOTSTRAP_KEY: &str = "AzzS";
pub const RESPONSE_KEY: &str = "AzzSystem";
pub const TIMEZONE: &str = "Asia/Ho_Chi_Minh";
pub const PORTAL_BASE_URL: &str = "https://qldtbeta.phenikaa-uni.edu.vn";
pub const CALENDAR_ACTION: &str = "SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv";
pub const CALENDAR_ACTION_KEY: &str = "DSA4BRINKCIpAiAPKSAv";
pub const CALENDAR_API_PATH: &str = "/sinhvienapi3/api/SV_ThongTin_MH/DSA4BRINKCIpAiAPKSAv";

static BOOTSTRAP_REGEX: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"AXYZCLRVN\s*=\s*\(\)\s*=>\s*["']([^"']+)["']"#).unwrap());

#[derive(Error, Debug)]
pub enum CryptoError {
    #[error("key must not be empty")]
    EmptyKey,
    #[error("invalid character code point {0}")]
    InvalidChar(u32),
    #[error("base64 error: {0}")]
    Base64(#[from] base64::DecodeError),
    #[error("utf8 error: {0}")]
    Utf8(#[from] std::string::FromUtf8Error),
    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("bootstrap data is invalid: {0}")]
    InvalidBootstrap(String),
    #[error("AXYZCLRVN bootstrap blob was not found in the authenticated HTML")]
    BootstrapMarkerNotFound,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BootstrapSession {
    #[serde(rename = "userId")]
    pub user_id: String,
    #[serde(rename = "tokenJWT")]
    pub token_jwt: String,
    #[serde(rename = "rootPath", default)]
    pub root_path: Option<String>,
    #[serde(flatten)]
    pub extra: std::collections::HashMap<String, serde_json::Value>,
}

pub fn xor_b64_encode(text: &str, key: &str) -> Result<String, CryptoError> {
    if key.is_empty() {
        return Err(CryptoError::EmptyKey);
    }
    let key_chars: Vec<u32> = key.chars().map(|c| c as u32).collect();
    let mut encrypted = String::with_capacity(text.len());
    for (i, c) in text.chars().enumerate() {
        let k = key_chars[i % key_chars.len()];
        let xored = (c as u32) ^ k;
        let ch = char::from_u32(xored).ok_or(CryptoError::InvalidChar(xored))?;
        encrypted.push(ch);
    }
    Ok(B64.encode(encrypted.as_bytes()))
}

pub fn xor_b64_decode(encoded: &str, key: &str) -> Result<String, CryptoError> {
    if key.is_empty() {
        return Err(CryptoError::EmptyKey);
    }
    let raw = B64.decode(encoded.trim())?;
    let intermediate = String::from_utf8(raw)?;
    let key_chars: Vec<u32> = key.chars().map(|c| c as u32).collect();
    let mut result = String::with_capacity(intermediate.len());
    for (i, c) in intermediate.chars().enumerate() {
        let k = key_chars[i % key_chars.len()];
        let xored = (c as u32) ^ k;
        let ch = char::from_u32(xored).ok_or(CryptoError::InvalidChar(xored))?;
        result.push(ch);
    }
    Ok(result)
}

pub fn decode_bootstrap_blob(blob: &str) -> Result<BootstrapSession, CryptoError> {
    let decoded = xor_b64_decode(blob, BOOTSTRAP_KEY)
        .map_err(|e| CryptoError::InvalidBootstrap(e.to_string()))?;
    let val: serde_json::Value = serde_json::from_str(&decoded)
        .map_err(|e| CryptoError::InvalidBootstrap(e.to_string()))?;
    if !val.is_object() {
        return Err(CryptoError::InvalidBootstrap("expected json object".into()));
    }
    let session: BootstrapSession = serde_json::from_value(val)
        .map_err(|e| CryptoError::InvalidBootstrap(e.to_string()))?;
    if session.user_id.is_empty() || session.token_jwt.is_empty() {
        return Err(CryptoError::InvalidBootstrap("missing userId or tokenJWT".into()));
    }
    Ok(session)
}

pub fn parse_bootstrap_html(html: &str) -> Result<BootstrapSession, CryptoError> {
    let caps = BOOTSTRAP_REGEX
        .captures(html)
        .ok_or(CryptoError::BootstrapMarkerNotFound)?;
    let blob = caps.get(1).unwrap().as_str();
    decode_bootstrap_blob(blob)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_xor_base64_round_trip_unicode() {
        let text = r#"{"course": "Xử lý ngôn ngữ tự nhiên"}"#;
        let key = "DSA4BRINKCIpAiAPKSAv";
        let encoded = xor_b64_encode(text, key).unwrap();
        assert_eq!(encoded, "P3EiWzcgOitpeWlSGeG6hGE8wrZzLxHCsD1hWiXhur1pOuG6umMnGCjCgy9yNg==");
        let decoded = xor_b64_decode(&encoded, key).unwrap();
        assert_eq!(decoded, text);
    }

    #[test]
    fn test_bootstrap_blob_and_html() {
        let session = BootstrapSession {
            user_id: "student-123".into(),
            token_jwt: "secret-token".into(),
            root_path: Some("/congsinhvien".into()),
            extra: Default::default(),
        };
        let json_text = serde_json::to_string(&session).unwrap();
        let blob = xor_b64_encode(&json_text, BOOTSTRAP_KEY).unwrap();

        let parsed = decode_bootstrap_blob(&blob).unwrap();
        assert_eq!(parsed.user_id, "student-123");
        assert_eq!(parsed.token_jwt, "secret-token");

        let html = format!(r#"<script>AXYZCLRVN = () => "{blob}"</script>"#);
        let html_parsed = parse_bootstrap_html(&html).unwrap();
        assert_eq!(html_parsed.user_id, "student-123");
    }

    #[test]
    fn test_decode_bootstrap_rejects_array() {
        let blob = xor_b64_encode("[]", BOOTSTRAP_KEY).unwrap();
        assert!(decode_bootstrap_blob(&blob).is_err());
    }
}
