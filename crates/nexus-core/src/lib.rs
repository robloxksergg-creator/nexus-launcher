//! Transfer integrity only. No network, paths, filesystem mutation or execution authority.
#![forbid(unsafe_code)]

use sha2::{Digest, Sha256};
use std::fmt;

pub mod archive;
pub mod catalog;
pub mod launch;
pub mod minecraft_classpath;
pub mod minecraft_command;
pub mod minecraft_profile;
pub mod minecraft_rules;

pub const MAX_FILE_BYTES: u64 = 1024 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TransferError {
    InvalidDigest,
    InvalidSize,
    TooLarge,
    SizeMismatch,
    DigestMismatch,
    Closed,
}

impl fmt::Display for TransferError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::InvalidDigest => "Expected SHA-256 must contain exactly 64 hex digits",
            Self::InvalidSize => "Expected size exceeds the file limit",
            Self::TooLarge => "Transfer exceeds its byte limit",
            Self::SizeMismatch => "Transfer size does not match expected size",
            Self::DigestMismatch => "Transfer SHA-256 does not match expected digest",
            Self::Closed => "Transfer verifier is closed",
        })
    }
}

impl std::error::Error for TransferError {}

/// A failed or completed attempt cannot be reused. Retrying requires a new verifier.
pub struct TransferVerifier {
    expected: [u8; 32],
    expected_size: Option<u64>,
    received: u64,
    hasher: Option<Sha256>,
}

impl TransferVerifier {
    pub fn new(digest: &str, expected_size: Option<u64>) -> Result<Self, TransferError> {
        if expected_size.is_some_and(|size| size > MAX_FILE_BYTES) {
            return Err(TransferError::InvalidSize);
        }
        let text = digest.as_bytes();
        if text.len() != 64 || !text.iter().all(u8::is_ascii_hexdigit) {
            return Err(TransferError::InvalidDigest);
        }
        let mut expected = [0; 32];
        for (i, pair) in text.as_chunks::<2>().0.iter().enumerate() {
            fn nibble(c: u8) -> u8 {
                match c {
                    b'0'..=b'9' => c - b'0',
                    b'a'..=b'f' => c - b'a' + 10,
                    _ => c - b'A' + 10, // ASCII hex validated above.
                }
            }
            expected[i] = (nibble(pair[0]) << 4) | nibble(pair[1]);
        }
        Ok(Self {
            expected,
            expected_size,
            received: 0,
            hasher: Some(Sha256::new()),
        })
    }

    pub fn received(&self) -> u64 {
        self.received
    }

    /// Reject an oversized chunk before hashing it or changing the byte count.
    pub fn update(&mut self, block: &[u8]) -> Result<(), TransferError> {
        if self.hasher.is_none() {
            return Err(TransferError::Closed);
        }
        let next = self.received.checked_add(block.len() as u64);
        let limit = self.expected_size.unwrap_or(MAX_FILE_BYTES);
        if next.is_none_or(|size| size > limit) {
            self.hasher = None;
            return Err(TransferError::TooLarge);
        }
        if let Some(hasher) = &mut self.hasher {
            hasher.update(block);
        }
        self.received = next.ok_or(TransferError::TooLarge)?;
        Ok(())
    }

    /// This confirms bytes only, never persistence, authenticity or a committed update.
    pub fn finish(&mut self) -> Result<u64, TransferError> {
        let hasher = self.hasher.take().ok_or(TransferError::Closed)?;
        if self.expected_size.is_some_and(|size| size != self.received) {
            return Err(TransferError::SizeMismatch);
        }
        let actual: [u8; 32] = hasher.finalize().into();
        if actual != self.expected {
            return Err(TransferError::DigestMismatch);
        }
        Ok(self.received)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    const ABC: &str = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";
    const EMPTY: &str = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    #[test]
    fn known_vectors_and_chunk_boundaries() {
        for chunks in [vec![&b"abc"[..]], vec![&b"a"[..], &b""[..], &b"bc"[..]]] {
            let mut verifier = TransferVerifier::new(ABC, Some(3)).unwrap();
            for chunk in chunks {
                verifier.update(chunk).unwrap();
            }
            assert_eq!(verifier.finish(), Ok(3));
            assert_eq!(verifier.finish(), Err(TransferError::Closed));
            assert_eq!(verifier.update(b""), Err(TransferError::Closed));
        }
    }

    #[test]
    fn empty_and_unknown_length() {
        assert_eq!(
            TransferVerifier::new(EMPTY, Some(0)).unwrap().finish(),
            Ok(0)
        );
        let mut verifier = TransferVerifier::new(&ABC.to_uppercase(), None).unwrap();
        verifier.update(b"abc").unwrap();
        assert_eq!(verifier.finish(), Ok(3));
    }

    #[test]
    fn invalid_configuration() {
        for digest in ["", "abc", &"g".repeat(64), &"é".repeat(32)] {
            assert!(matches!(
                TransferVerifier::new(digest, None),
                Err(TransferError::InvalidDigest)
            ));
        }
        assert!(matches!(
            TransferVerifier::new(ABC, Some(MAX_FILE_BYTES + 1)),
            Err(TransferError::InvalidSize)
        ));
    }

    #[test]
    fn overflow_poisons_attempt_without_accepting_chunk() {
        let mut verifier = TransferVerifier::new(ABC, Some(3)).unwrap();
        verifier.update(b"a").unwrap();
        assert_eq!(verifier.update(b"bcd"), Err(TransferError::TooLarge));
        assert_eq!(verifier.received(), 1);
        assert_eq!(verifier.update(b"bc"), Err(TransferError::Closed));
        assert_eq!(verifier.finish(), Err(TransferError::Closed));
    }

    #[test]
    fn truncated_and_corrupted_attempts_are_terminal() {
        let mut short = TransferVerifier::new(ABC, Some(3)).unwrap();
        short.update(b"ab").unwrap();
        assert_eq!(short.finish(), Err(TransferError::SizeMismatch));
        assert_eq!(short.finish(), Err(TransferError::Closed));
        let mut corrupt = TransferVerifier::new(ABC, None).unwrap();
        corrupt.update(b"abd").unwrap();
        assert_eq!(corrupt.finish(), Err(TransferError::DigestMismatch));
        assert_eq!(corrupt.update(b"abc"), Err(TransferError::Closed));
    }

    #[test]
    fn global_byte_limit_without_allocating_a_gigabyte() {
        let mut verifier = TransferVerifier::new(ABC, None).unwrap();
        // Internal boundary setup; no claim that these bytes were actually hashed.
        verifier.received = MAX_FILE_BYTES;
        assert_eq!(verifier.update(b"x"), Err(TransferError::TooLarge));
        assert_eq!(verifier.received(), MAX_FILE_BYTES);
    }
}
