//! Raw ZIP DEFLATE only. Parsing, paths, CRC and file ownership stay in Python.
use flate2::{Decompress, FlushDecompress, Status};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

const CHUNK: usize = 1024 * 1024;

#[pyclass(module = "_nexus_launcher_core")]
pub struct ZipDeflateDecoder {
    inner: Decompress,
    size: u64,
    compressed: u64,
    tail: Vec<u8>,
    eof: bool,
    failed: bool,
    verified: bool,
}

impl ZipDeflateDecoder {
    fn refuse(&mut self, reason: &str) -> PyErr {
        self.failed = true;
        PyValueError::new_err(reason.to_owned())
    }

    fn decode(&mut self, data: &[u8], max_length: usize, flush: bool) -> PyResult<Vec<u8>> {
        if self.failed || self.verified || max_length == 0 || data.len() > CHUNK {
            return Err(self.refuse("Invalid or closed ZIP decoder"));
        }
        if self.eof {
            if data.is_empty() {
                return Ok(Vec::new());
            }
            return Err(self.refuse("Trailing ZIP DEFLATE input"));
        }
        let before_in = self.inner.total_in();
        let before_out = self.inner.total_out();
        if data.len() as u64 > self.compressed.saturating_sub(before_in) {
            return Err(self.refuse("ZIP compressed size exceeded"));
        }
        let remaining = self.size.saturating_sub(before_out);
        let budget = max_length.min(CHUNK) as u64;
        // At the declared boundary reserve a probe byte so an exact-sized
        // stream can consume its end marker, while overproduction is refused.
        let capacity = if remaining <= budget {
            remaining + 1
        } else {
            budget
        };
        let mut output = vec![0; capacity as usize];
        let mode = if flush {
            FlushDecompress::Finish
        } else {
            FlushDecompress::None
        };
        let status = self
            .inner
            .decompress(data, &mut output, mode)
            .map_err(|_| self.refuse("Invalid ZIP DEFLATE stream"))?;
        let consumed = (self.inner.total_in() - before_in) as usize;
        let produced = (self.inner.total_out() - before_out) as usize;
        if self.inner.total_out() > self.size {
            return Err(self.refuse("ZIP decompressed size exceeded"));
        }
        self.eof = status == Status::StreamEnd;
        self.tail = data[consumed..].to_vec();
        if self.eof && !self.tail.is_empty() {
            return Err(self.refuse("Trailing ZIP DEFLATE input"));
        }
        if flush && !self.eof {
            return Err(self.refuse("Incomplete ZIP DEFLATE stream"));
        }
        if consumed == 0
            && produced == 0
            && !data.is_empty()
            && before_in + data.len() as u64 == self.compressed
        {
            return Err(self.refuse("Stalled ZIP DEFLATE stream"));
        }
        output.truncate(produced);
        Ok(output)
    }
}

#[pymethods]
impl ZipDeflateDecoder {
    #[new]
    #[pyo3(signature = (size, compressed, *, limit=1073741824))]
    fn new(size: u64, compressed: u64, limit: u64) -> PyResult<Self> {
        let compressed_limit = if limit <= 1024 * 1024 * 1024 {
            4 * 1024 * 1024 * 1024
        } else {
            16 * 1024 * 1024 * 1024
        };
        if limit > 16 * 1024 * 1024 * 1024 || size > limit || compressed > compressed_limit {
            return Err(PyValueError::new_err("ZIP entry exceeds decoder limits"));
        }
        Ok(Self {
            inner: Decompress::new(false),
            size,
            compressed,
            tail: Vec::new(),
            eof: false,
            failed: false,
            verified: false,
        })
    }

    fn decompress(
        &mut self,
        py: Python<'_>,
        data: &[u8],
        max_length: usize,
    ) -> PyResult<Py<PyBytes>> {
        let output = py.detach(|| self.decode(data, max_length, false))?;
        Ok(PyBytes::new(py, &output).unbind())
    }

    fn flush(&mut self, py: Python<'_>) -> PyResult<Py<PyBytes>> {
        let output = py.detach(|| self.decode(&[], CHUNK, true))?;
        Ok(PyBytes::new(py, &output).unbind())
    }

    #[getter]
    fn unconsumed_tail(&self, py: Python<'_>) -> Py<PyBytes> {
        PyBytes::new(py, &self.tail).unbind()
    }

    #[getter]
    fn eof(&self) -> bool {
        self.eof
    }

    fn verify_complete(&mut self) -> PyResult<()> {
        if self.failed
            || self.verified
            || !self.eof
            || !self.tail.is_empty()
            || self.inner.total_in() != self.compressed
            || self.inner.total_out() != self.size
        {
            return Err(self.refuse("ZIP entry completion not proven"));
        }
        self.verified = true;
        Ok(())
    }
}
