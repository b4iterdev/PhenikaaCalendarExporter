use fernet::Fernet;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::Path;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum CryptoError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid fernet key")]
    InvalidKey,
    #[error("stored credential could not be decrypted with the server key")]
    DecryptionFailed,
}

pub fn load_or_create_key<P: AsRef<Path>>(path: P) -> Result<String, CryptoError> {
    let p = path.as_ref();
    if p.exists() {
        let content = fs::read_to_string(p)?;
        let trimmed = content.trim();
        if !trimmed.is_empty() {
            return Ok(trimmed.to_string());
        }
    }

    if let Some(parent) = p.parent() {
        fs::create_dir_all(parent)?;
    }

    let key = Fernet::generate_key();
    fs::write(p, &key)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = fs::metadata(p)?.permissions();
        perms.set_mode(0o600);
        fs::set_permissions(p, perms)?;
    }

    Ok(key)
}

pub fn token_fingerprint(token: Option<&str>) -> Option<String> {
    token.map(|t| {
        let mut hasher = Sha256::new();
        hasher.update(t.as_bytes());
        let hash = format!("{:x}", hasher.finalize());
        hash[..12].to_string()
    })
}

#[derive(Clone)]
pub struct TokenVault {
    fernet: Fernet,
}

impl TokenVault {
    pub fn new(key: &str) -> Result<Self, CryptoError> {
        let fernet = Fernet::new(key).ok_or(CryptoError::InvalidKey)?;
        Ok(Self { fernet })
    }

    pub fn encrypt(&self, plain: &str) -> String {
        self.fernet.encrypt(plain.as_bytes())
    }

    pub fn decrypt(&self, cipher: &str) -> Result<String, CryptoError> {
        let bytes = self
            .fernet
            .decrypt(cipher)
            .map_err(|_| CryptoError::DecryptionFailed)?;
        String::from_utf8(bytes).map_err(|_| CryptoError::DecryptionFailed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_vault_round_trip() {
        let key = Fernet::generate_key();
        let vault = TokenVault::new(&key).unwrap();
        let secret = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test";
        let encrypted = vault.encrypt(secret);
        let decrypted = vault.decrypt(&encrypted).unwrap();
        assert_eq!(decrypted, secret);
    }

    #[test]
    fn test_token_fingerprint() {
        assert_eq!(token_fingerprint(None), None);
        let fp = token_fingerprint(Some("test-token")).unwrap();
        assert_eq!(fp.len(), 12);
    }
}
