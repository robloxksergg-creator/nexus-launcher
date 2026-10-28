//! ZIP metadata size policy only; no parsing, extraction or path authorization.

use std::fmt;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ArchiveError {
    EntryCount,
    FileSize,
    TotalSize,
}

impl fmt::Display for ArchiveError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::EntryCount => "Too many archive entries",
            Self::FileSize => "Archive file exceeds size limit",
            Self::TotalSize => "Archive exceeds extracted byte limit",
        })
    }
}

impl std::error::Error for ArchiveError {}

/// Limits come from the caller's existing installation policy. Metadata sizes
/// are not evidence of actual decompressed bytes; extraction must remain bounded.
pub fn validate_sizes(
    sizes: &[i128],
    max_entries: usize,
    max_file: u64,
    max_total: u64,
) -> Result<u64, ArchiveError> {
    if sizes.len() > max_entries {
        return Err(ArchiveError::EntryCount);
    }
    let mut total = 0_u64;
    for &size in sizes {
        if size < 0 || size > i128::from(max_file) {
            return Err(ArchiveError::FileSize);
        }
        let size = u64::try_from(size).map_err(|_| ArchiveError::FileSize)?;
        total = total.checked_add(size).ok_or(ArchiveError::TotalSize)?;
        if total > max_total {
            return Err(ArchiveError::TotalSize);
        }
    }
    Ok(total)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_zero_and_exact_limits() {
        assert_eq!(validate_sizes(&[], 0, 0, 0), Ok(0));
        assert_eq!(validate_sizes(&[0, 2, 3], 3, 3, 5), Ok(5));
        assert_eq!(validate_sizes(&[0; 50_000], 50_000, 0, 0), Ok(0));
    }

    #[test]
    fn entry_limit_is_checked_before_sizes() {
        assert_eq!(
            validate_sizes(&[-1], 0, 0, 0),
            Err(ArchiveError::EntryCount)
        );
    }

    #[test]
    fn negative_and_oversized_files() {
        for size in [-1, 4, i128::MAX] {
            assert_eq!(
                validate_sizes(&[size], 1, 3, 9),
                Err(ArchiveError::FileSize)
            );
        }
    }

    #[test]
    fn total_limit_and_overflow_fail_closed() {
        assert_eq!(
            validate_sizes(&[3, 3], 2, 3, 5),
            Err(ArchiveError::TotalSize)
        );
        assert_eq!(
            validate_sizes(&[i128::from(u64::MAX), 1], 2, u64::MAX, u64::MAX),
            Err(ArchiveError::TotalSize)
        );
    }

    #[test]
    fn refuses_without_modifying_inventory() {
        let sizes = [1, 3, 2];
        let before = sizes;
        for _ in 0..2 {
            assert_eq!(validate_sizes(&sizes, 3, 2, 9), Err(ArchiveError::FileSize));
            assert_eq!(sizes, before);
        }
    }
}
