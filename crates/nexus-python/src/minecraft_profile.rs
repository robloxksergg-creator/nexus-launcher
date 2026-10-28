//! Pure inheritance bridge. Does not read or select parent profile files.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
pub fn minecraft_inherit_profile(py: Python<'_>, child: &str, parent: &str) -> PyResult<String> {
    py.detach(|| nexus_core::minecraft_profile::inherit(child, parent))
        .map_err(|error| PyValueError::new_err(error.to_string()))
}
