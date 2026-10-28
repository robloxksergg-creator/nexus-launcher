//! Typed command plan bridge; never executes the resulting argument vector.
use nexus_core::minecraft_command::{CommandPlan, compose};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

#[pyfunction]
pub fn minecraft_compose_command(
    py: Python<'_>,
    request: &Bound<'_, PyDict>,
) -> PyResult<Vec<String>> {
    if request.len() != 10 {
        return Err(PyValueError::new_err("Invalid command plan fields"));
    }
    macro_rules! field {
        ($name:literal, $kind:ty) => {
            request
                .get_item($name)?
                .ok_or_else(|| PyValueError::new_err("Missing command plan field"))?
                .extract::<$kind>()?
        };
    }
    let plan = CommandPlan {
        executable: field!("executable", String),
        user_jvm: field!("user_jvm", Vec<String>),
        metadata_jvm: field!("metadata_jvm", Option<Vec<String>>),
        fallback_jvm: field!("fallback_jvm", Vec<String>),
        main_class: field!("main_class", String),
        game: field!("game", Vec<String>),
        replacements: field!("replacements", Vec<(String, String)>),
        game_extras: field!("game_extras", Vec<String>),
        tail: field!("tail", Vec<String>),
        logging: field!("logging", Option<String>),
    };
    py.detach(|| compose(plan))
        .map_err(|error| PyValueError::new_err(error.to_string()))
}
