//! Typed launch policy bridge. Never spawns Java or receives environment values.
use pyo3::prelude::*;

#[pyfunction]
pub fn launch_username_valid(name: &str) -> bool {
    nexus_core::launch::valid_username(name)
}

#[pyfunction]
pub fn launch_environment_mask(uppercase_keys: Vec<String>) -> Vec<bool> {
    uppercase_keys
        .iter()
        .map(|key| nexus_core::launch::allowed_environment_key(key))
        .collect()
}

#[pyfunction]
pub fn launch_redact_command(command: Vec<String>) -> Vec<String> {
    nexus_core::launch::redact_command(&command)
}
