//! Rule control flow bridge; existing Python predicates retain regex/host semantics.
use nexus_core::minecraft_rules::{self, RuleError, RuleHost};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

struct PythonHost<'py> {
    architecture: Bound<'py, PyAny>,
    version: Bound<'py, PyAny>,
    error: Option<PyErr>,
}
impl PythonHost<'_> {
    fn result(&mut self, result: PyResult<bool>) -> Result<bool, RuleError> {
        result.map_err(|error| {
            self.error = Some(error);
            RuleError::HostPredicate
        })
    }
}
impl RuleHost for PythonHost<'_> {
    fn is_32bit(&mut self) -> Result<bool, RuleError> {
        let result = self.architecture.call0().and_then(|v| v.extract());
        self.result(result)
    }
    fn version_matches(&mut self, pattern: &str) -> Result<bool, RuleError> {
        let result = self.version.call1((pattern,)).and_then(|v| v.extract());
        self.result(result)
    }
}

#[pyfunction]
pub fn minecraft_rules_evaluate<'py>(
    rules: &str,
    system: &str,
    features: Vec<bool>,
    architecture: Bound<'py, PyAny>,
    version: Bound<'py, PyAny>,
) -> PyResult<bool> {
    let features: [bool; 6] = features
        .try_into()
        .map_err(|_| PyValueError::new_err("Invalid Minecraft rule feature vector"))?;
    let mut host = PythonHost {
        architecture,
        version,
        error: None,
    };
    match minecraft_rules::evaluate(rules, system, &features, &mut host) {
        Ok(result) => Ok(result),
        Err(error) => Err(host
            .error
            .unwrap_or_else(|| PyValueError::new_err(error.to_string()))),
    }
}
