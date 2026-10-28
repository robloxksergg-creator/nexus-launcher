//! Classpath planning bridge. No filesystem or Java runtime interaction.
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

#[pyfunction]
pub fn minecraft_classpath_entries(
    py: Python<'_>,
    profile: &str,
    selections: Vec<Option<String>>,
) -> PyResult<Vec<Vec<String>>> {
    py.detach(|| nexus_core::minecraft_classpath::entries(profile, &selections))
        .map_err(|error| PyValueError::new_err(error.to_string()))
}
