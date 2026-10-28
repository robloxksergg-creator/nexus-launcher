//! Stream orchestration only. Python retains stream ownership and decompression.
//! Callbacks can block; deadlines are checks between calls, not cancellation.

use pyo3::exceptions::{PyOSError, PyTimeoutError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use sha2::{Digest, Sha256, Sha512};

fn now(clock: &Bound<'_, PyAny>) -> PyResult<f64> {
    clock.call0()?.extract()
}

fn deadline(clock: &Bound<'_, PyAny>, timeout: f64) -> PyResult<f64> {
    if !timeout.is_finite() || timeout < 0.0 {
        return Err(PyValueError::new_err("Invalid stream time budget"));
    }
    Ok(now(clock)? + timeout)
}

fn hash_stream<D: Digest + Default + Send>(
    py: Python<'_>,
    read: &Bound<'_, PyAny>,
    limit: u64,
    timeout: f64,
    clock: &Bound<'_, PyAny>,
) -> PyResult<String> {
    let end = deadline(clock, timeout)?;
    let mut total = 0_u64;
    let mut hasher = D::default();
    loop {
        if now(clock)? >= end {
            return Err(PyTimeoutError::new_err("Hashing exceeded its time budget"));
        }
        let request = (limit - total).saturating_add(1).min(256 * 1024);
        let block = read.call1((request,))?;
        if now(clock)? >= end {
            return Err(PyTimeoutError::new_err("Hashing exceeded its time budget"));
        }
        let block = block.cast::<PyBytes>()?;
        let bytes = block.as_bytes();
        if bytes.is_empty() {
            let raw = hasher.finalize();
            let mut hex = String::with_capacity(raw.len() * 2);
            const HEX: &[u8; 16] = b"0123456789abcdef";
            for &byte in raw.iter() {
                hex.push(HEX[(byte >> 4) as usize] as char);
                hex.push(HEX[(byte & 15) as usize] as char);
            }
            return Ok(hex);
        }
        let count = bytes.len() as u64;
        if count > limit - total {
            return Err(PyValueError::new_err("Hash input exceeds byte limit"));
        }
        // Immutable bytes remain borrowed and alive while CPU hashing runs
        // outside the GIL. The caller retains ownership of the stream.
        py.detach(|| hasher.update(bytes));
        total += count;
    }
}

#[pyfunction]
pub fn stream_digest_limited(
    py: Python<'_>,
    read: &Bound<'_, PyAny>,
    algorithm: &str,
    limit: u64,
    timeout: f64,
    clock: &Bound<'_, PyAny>,
) -> PyResult<String> {
    match algorithm {
        "sha256" => hash_stream::<Sha256>(py, read, limit, timeout, clock),
        "sha512" => hash_stream::<Sha512>(py, read, limit, timeout, clock),
        _ => Err(PyValueError::new_err("Unsupported stream digest")),
    }
}

#[pyfunction]
pub fn stream_read_limited(
    py: Python<'_>,
    read: &Bound<'_, PyAny>,
    limit: u64,
    timeout: f64,
    clock: &Bound<'_, PyAny>,
) -> PyResult<Py<PyBytes>> {
    let end = deadline(clock, timeout)?;
    let mut output = Vec::new();
    loop {
        if now(clock)? >= end {
            return Err(PyTimeoutError::new_err("Response exceeded its time budget"));
        }
        let remaining = limit - output.len() as u64;
        let request = remaining.saturating_add(1).min(64 * 1024);
        let block = read.call1((request,))?;
        if now(clock)? >= end {
            return Err(PyTimeoutError::new_err("Response exceeded its time budget"));
        }
        let block = block.cast::<PyBytes>()?;
        if block.as_bytes().is_empty() {
            return Ok(PyBytes::new(py, &output).unbind());
        }
        if block.as_bytes().len() as u64 > remaining {
            return Err(PyValueError::new_err("Response exceeds byte limit"));
        }
        output.extend_from_slice(block.as_bytes());
    }
}

#[pyfunction]
pub fn stream_copy_limited(
    read: &Bound<'_, PyAny>,
    write: &Bound<'_, PyAny>,
    limit: u64,
    digest: &Bound<'_, PyAny>,
    timeout: f64,
    clock: &Bound<'_, PyAny>,
) -> PyResult<u64> {
    let end = deadline(clock, timeout)?;
    let mut total = 0_u64;
    loop {
        let request = (limit - total).saturating_add(1).min(256 * 1024);
        let block = read.call1((request,))?;
        let bytes = block.cast::<PyBytes>()?;
        let count = bytes.as_bytes().len() as u64;
        if count == 0 {
            return Ok(total);
        }
        if now(clock)? > end {
            return Err(PyTimeoutError::new_err(
                "File transfer exceeded its time budget",
            ));
        }
        if count > limit - total {
            return Err(PyValueError::new_err("File exceeds byte limit"));
        }
        // Never report a completed copy or update its digest on short writes.
        let written = write.call1((&block,))?;
        if written.extract::<u64>().ok() != Some(count) {
            return Err(PyOSError::new_err("Incomplete stream write"));
        }
        if !digest.is_none() {
            digest.call_method1("update", (&block,))?;
        }
        total += count;
    }
}
