//! Bounded metadata bridge. Does not read or extract archive contents.

use nexus_core::archive::{ArchiveError, validate_sizes};
use pyo3::exceptions::{PyOverflowError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyList;

#[pyfunction]
pub fn archive_inventory(
    py: Python<'_>,
    sizes: &Bound<'_, PyList>,
    max_entries: usize,
    max_file_bytes: u64,
    max_extracted_bytes: u64,
) -> PyResult<u64> {
    // Bound conversion/allocation before extracting any elements.
    if sizes.len() > max_entries {
        return Err(PyValueError::new_err(ArchiveError::EntryCount.to_string()));
    }
    let mut values = Vec::with_capacity(sizes.len());
    for item in sizes.iter() {
        values.push(item.extract::<i128>().or_else(|error| {
            if error.is_instance_of::<PyOverflowError>(py) {
                // An out-of-range Python integer is necessarily an invalid
                // file size. Keep its position so earlier total-limit errors
                // retain the same precedence as the Python implementation.
                Ok(i128::MAX)
            } else {
                Err(error)
            }
        })?);
    }
    py.detach(|| validate_sizes(&values, max_entries, max_file_bytes, max_extracted_bytes))
        .map_err(|error| PyValueError::new_err(error.to_string()))
}
