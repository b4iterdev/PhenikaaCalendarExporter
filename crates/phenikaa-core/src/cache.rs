use crate::crypto::{parse_bootstrap_html, BootstrapSession, CryptoError};
use flate2::read::GzDecoder;
use std::fs;
use std::io::Read;
use std::path::Path;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum CacheError {
    #[error("cache directory does not exist: {0}")]
    NotFound(String),
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("no authenticated Phenikaa bootstrap page was found in the Chromium cache")]
    NoAuthFound,
    #[error("crypto error: {0}")]
    Crypto(#[from] CryptoError),
}

pub fn default_cache_dir() -> Option<std::path::PathBuf> {
    if let Ok(home) = std::env::var("HOME") {
        let p = std::path::PathBuf::from(home);
        // macOS
        let mac_chrome = p.join("Library/Caches/Google/Chrome/Default/Cache/Cache_Data");
        if mac_chrome.is_dir() {
            return Some(mac_chrome);
        }
        let mac_chromium = p.join("Library/Caches/Chromium/Default/Cache/Cache_Data");
        if mac_chromium.is_dir() {
            return Some(mac_chromium);
        }
        // Linux
        let linux_chrome = p.join(".cache/google-chrome/Default/Cache/Cache_Data");
        if linux_chrome.is_dir() {
            return Some(linux_chrome);
        }
        let linux_chromium = p.join(".cache/chromium/Default/Cache/Cache_Data");
        if linux_chromium.is_dir() {
            return Some(linux_chromium);
        }
    }
    None
}

pub fn extract_auth_from_cache<P: AsRef<Path>>(cache_dir: P) -> Result<BootstrapSession, CacheError> {
    let dir = cache_dir.as_ref();
    if !dir.is_dir() {
        return Err(CacheError::NotFound(dir.display().to_string()));
    }

    let mut entries = Vec::new();
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.is_file() {
            let mtime = entry
                .metadata()
                .and_then(|m| m.modified())
                .unwrap_or(std::time::SystemTime::UNIX_EPOCH);
            entries.push((path, mtime));
        }
    }

    // Sort newest first
    entries.sort_by(|a, b| b.1.cmp(&a.1));

    for (path, _) in entries {
        let data = match fs::read(&path) {
            Ok(d) => d,
            Err(_) => continue,
        };

        let has_index = data.windows(10).any(|w| w == b"index.aspx");
        let has_marker = data.windows(9).any(|w| w == b"AXYZCLRVN");
        if !has_index && !has_marker {
            continue;
        }

        // Search for gzip magic header 0x1f 0x8b 0x08
        for (idx, window) in data.windows(3).enumerate() {
            if window == [0x1f, 0x8b, 0x08] {
                let mut decoder = GzDecoder::new(&data[idx..]);
                let mut decompressed = Vec::new();
                if decoder.read_to_end(&mut decompressed).is_ok() {
                    let html = String::from_utf8_lossy(&decompressed);
                    if html.contains("AXYZCLRVN") {
                        if let Ok(sess) = parse_bootstrap_html(&html) {
                            return Ok(sess);
                        }
                    }
                }
            }
        }

        if has_marker {
            let html = String::from_utf8_lossy(&data);
            if let Ok(sess) = parse_bootstrap_html(&html) {
                return Ok(sess);
            }
        }
    }

    Err(CacheError::NoAuthFound)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crypto::{xor_b64_encode, BOOTSTRAP_KEY};
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use std::io::Write;

    #[test]
    fn test_extract_auth_from_cache() {
        let temp = tempfile::tempdir().unwrap();
        let payload = r#"{"userId":"student-id","tokenJWT":"secret-token"}"#;
        let blob = xor_b64_encode(payload, BOOTSTRAP_KEY).unwrap();
        let html = format!(r#"<html><script>AXYZCLRVN = () => "{blob}"</script></html>"#);

        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(html.as_bytes()).unwrap();
        let gz_data = encoder.finish().unwrap();

        let mut entry_bytes = b"cache-prefix\0https://portal/index.aspx\0".to_vec();
        entry_bytes.extend_from_slice(&gz_data);
        entry_bytes.extend_from_slice(b"cache-metadata");

        let entry_path = temp.path().join("entry_0");
        fs::write(&entry_path, entry_bytes).unwrap();

        let sess = extract_auth_from_cache(temp.path()).unwrap();
        assert_eq!(sess.user_id, "student-id");
        assert_eq!(sess.token_jwt, "secret-token");
    }
}
