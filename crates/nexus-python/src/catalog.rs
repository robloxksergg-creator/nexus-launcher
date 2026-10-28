//! JSON preflight bridge only; no file paths, IO or writer ownership.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
pub fn catalog_preflight_json(py: Python<'_>, input: &str) -> PyResult<String> {
    py.detach(|| nexus_core::catalog::preflight_json(input))
        .map_err(|error| PyValueError::new_err(error.to_string()))
}
