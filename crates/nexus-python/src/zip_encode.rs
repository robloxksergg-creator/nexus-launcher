//! Bounded raw DEFLATE encoder; ZIP framing and destination ownership are external.
use flate2::{Compress, Compression, FlushCompress, Status};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

const CHUNK: usize = 1024 * 1024;
const OUTPUT_LIMIT: usize = CHUNK + 256 * 1024;

#[pyclass(module = "_nexus_launcher_core")]
pub struct ZipDeflateEncoder {
    inner: Compress,
    failed: bool,
    finished: bool,
    limit: u64,
}

impl ZipDeflateEncoder {
    fn refuse(&mut self, reason: &str) -> PyErr {
        self.failed = true;
        PyValueError::new_err(reason.to_owned())
    }

    fn run(&mut self, data: &[u8], finish: bool) -> PyResult<Vec<u8>> {
        if self.failed || self.finished || data.len() > CHUNK {
            return Err(self.refuse("Invalid or closed ZIP encoder"));
        }
        if self.inner.total_in() + data.len() as u64 > self.limit {
            return Err(self.refuse("ZIP input size exceeded"));
        }
        let mut result = Vec::new();
        let mut offset = 0;
        loop {
            let before_in = self.inner.total_in();
            let before_out = self.inner.total_out();
            let mut output = vec![0; 64 * 1024];
            let mode = if finish {
                FlushCompress::Finish
            } else {
                FlushCompress::None
            };
            let status = self
                .inner
                .compress(&data[offset..], &mut output, mode)
                .map_err(|_| self.refuse("ZIP DEFLATE encoding failed"))?;
            let consumed = (self.inner.total_in() - before_in) as usize;
            let produced = (self.inner.total_out() - before_out) as usize;
            if result.len() + produced > OUTPUT_LIMIT {
                return Err(self.refuse("ZIP encoder output budget exceeded"));
            }
            result.extend_from_slice(&output[..produced]);
            offset += consumed;
            if finish && status == Status::StreamEnd {
                self.finished = true;
                break;
            }
            if !finish && offset == data.len() {
                break;
            }
            if consumed == 0 && produced == 0 {
                return Err(self.refuse("Stalled ZIP encoder"));
            }
        }
        Ok(result)
    }
}

#[pymethods]
impl ZipDeflateEncoder {
    #[new]
    #[pyo3(signature = (level, *, limit=1073741824))]
    fn new(level: u32, limit: u64) -> PyResult<Self> {
        if limit > 16 * 1024 * 1024 * 1024 {
            return Err(PyValueError::new_err("Invalid ZIP encoder byte limit"));
        }
        if level > 9 {
            return Err(PyValueError::new_err("Invalid ZIP compression level"));
        }
        Ok(Self {
            inner: Compress::new(Compression::new(level), false),
            failed: false,
            finished: false,
            limit,
        })
    }

    fn compress(&mut self, py: Python<'_>, data: &[u8]) -> PyResult<Py<PyBytes>> {
        let result = py.detach(|| self.run(data, false))?;
        Ok(PyBytes::new(py, &result).unbind())
    }

    fn flush(&mut self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        let result = py.detach(|| self.run(&[], true))?;
        Ok(PyBytes::new(py, &result).unbind())
    }

    fn verify_complete(&self, expected: u64) -> PyResult<()> {
        if self.failed || !self.finished || self.inner.total_in() != expected {
            return Err(PyValueError::new_err("ZIP encoding completion not proven"));
        }
        Ok(())
    }
}
