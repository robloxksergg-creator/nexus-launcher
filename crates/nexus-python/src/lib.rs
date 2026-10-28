mod catalog;
mod launch_policy;
mod minecraft_classpath;
mod minecraft_command;
mod minecraft_profile;
mod minecraft_rules;
use nexus_core::{TransferError, TransferVerifier};
use nexus_transport::{DownloadClient, DownloadError, DownloadResponse};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;
mod archive;
#[cfg(windows)]
mod safe_io;
mod stream_io;
mod transaction;
mod zip_codec;
mod zip_encode;

fn download_error(error: DownloadError) -> PyErr {
    match error {
        DownloadError::Policy(_) => PyValueError::new_err(error.to_string()),
        DownloadError::Timeout => pyo3::exceptions::PyTimeoutError::new_err(error.to_string()),
        _ => pyo3::exceptions::PyOSError::new_err(error.to_string()),
    }
}

#[pyclass(name = "DownloadClient", module = "_nexus_launcher_core")]
struct PyDownloadClient {
    inner: DownloadClient,
}

#[pymethods]
impl PyDownloadClient {
    #[new]
    fn new(py: Python<'_>) -> PyResult<Self> {
        py.detach(DownloadClient::new)
            .map(|inner| Self { inner })
            .map_err(download_error)
    }

    fn open(
        &self,
        py: Python<'_>,
        url: String,
        hosts: Vec<String>,
        headers: Vec<(String, String)>,
        timeout: f64,
    ) -> PyResult<PyDownloadResponse> {
        py.detach(|| self.inner.open(&url, hosts, headers, timeout))
            .map(|inner| PyDownloadResponse { inner })
            .map_err(download_error)
    }
}

#[pyclass(name = "DownloadResponse", module = "_nexus_launcher_core")]
struct PyDownloadResponse {
    inner: DownloadResponse,
}

#[pymethods]
impl PyDownloadResponse {
    fn read1(&mut self, py: Python<'_>, limit: usize) -> PyResult<Py<PyBytes>> {
        let data = py
            .detach(|| self.inner.read1(limit))
            .map_err(download_error)?;
        Ok(PyBytes::new(py, &data).unbind())
    }

    fn close(&mut self) {
        self.inner.close();
    }
    #[getter]
    fn status(&self) -> u16 {
        self.inner.status
    }
    #[getter]
    fn headers(&self) -> Vec<(String, String)> {
        self.inner.headers.clone()
    }
    fn geturl(&self) -> &str {
        &self.inner.url
    }
}

fn as_python_error(error: TransferError) -> PyErr {
    PyValueError::new_err(error.to_string())
}

#[pyclass(name = "TransferVerifier", module = "_nexus_launcher_core")]
struct PyTransferVerifier {
    inner: TransferVerifier,
}

#[pymethods]
impl PyTransferVerifier {
    #[new]
    #[pyo3(signature = (digest, expected_size=None))]
    fn new(digest: &str, expected_size: Option<u64>) -> PyResult<Self> {
        Ok(Self {
            inner: TransferVerifier::new(digest, expected_size).map_err(as_python_error)?,
        })
    }

    fn update(&mut self, py: Python<'_>, block: &[u8]) -> PyResult<()> {
        // PyO3 borrows immutable Python bytes. Hash outside the GIL so the UI
        // thread can continue while a download worker verifies a large chunk.
        py.detach(|| self.inner.update(block))
            .map_err(as_python_error)
    }

    fn finish(&mut self) -> PyResult<u64> {
        self.inner.finish().map_err(as_python_error)
    }

    #[getter]
    fn received(&self) -> u64 {
        self.inner.received()
    }
}

#[pymodule]
fn _nexus_launcher_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("CORE_API_VERSION", 1)?;
    module.add("HTTP_API_VERSION", 1)?;
    module.add("TRANSACTION_API_VERSION", 1)?;
    module.add("ARCHIVE_API_VERSION", 1)?;
    module.add("STREAM_IO_API_VERSION", 1)?;
    module.add("STREAM_HASH_API_VERSION", 1)?;
    module.add("ZIP_DEFLATE_API_VERSION", 1)?;
    module.add("ZIP_ENCODE_API_VERSION", 1)?;
    module.add("ZIP_LIMITS_API_VERSION", 1)?;
    module.add("LAUNCH_POLICY_API_VERSION", 1)?;
    module.add("CATALOG_API_VERSION", 1)?;
    module.add("MINECRAFT_COMMAND_API_VERSION", 1)?;
    module.add("MINECRAFT_PROFILE_API_VERSION", 1)?;
    module.add("MINECRAFT_CLASSPATH_API_VERSION", 1)?;
    module.add("MINECRAFT_RULES_API_VERSION", 1)?;
    module.add_function(wrap_pyfunction!(
        minecraft_rules::minecraft_rules_evaluate,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        minecraft_classpath::minecraft_classpath_entries,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        minecraft_profile::minecraft_inherit_profile,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        minecraft_command::minecraft_compose_command,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(catalog::catalog_preflight_json, module)?)?;
    module.add_function(wrap_pyfunction!(
        launch_policy::launch_username_valid,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        launch_policy::launch_environment_mask,
        module
    )?)?;
    module.add_function(wrap_pyfunction!(
        launch_policy::launch_redact_command,
        module
    )?)?;
    module.add_class::<zip_encode::ZipDeflateEncoder>()?;
    module.add_class::<zip_codec::ZipDeflateDecoder>()?;
    module.add_function(wrap_pyfunction!(stream_io::stream_digest_limited, module)?)?;
    module.add_function(wrap_pyfunction!(stream_io::stream_read_limited, module)?)?;
    module.add_function(wrap_pyfunction!(stream_io::stream_copy_limited, module)?)?;
    module.add_function(wrap_pyfunction!(archive::archive_inventory, module)?)?;
    #[cfg(windows)]
    {
        module.add("SAFE_IO_API_VERSION", 1)?;
        module.add("HANDLE_REPLACE_API_VERSION", 1)?;
        module.add("COPY_STREAM_API_VERSION", 1)?;
        module.add_function(wrap_pyfunction!(safe_io::windows_copy_streams, module)?)?;
        module.add_function(wrap_pyfunction!(safe_io::windows_replace_file, module)?)?;
        module.add_class::<safe_io::WindowsDirectoryPin>()?;
    }
    module.add_function(wrap_pyfunction!(transaction::transaction_apply, module)?)?;
    module.add_function(wrap_pyfunction!(transaction::transaction_recover, module)?)?;
    module.add_class::<PyTransferVerifier>()?;
    module.add_class::<PyDownloadClient>()?;
    module.add_class::<PyDownloadResponse>()?;
    Ok(())
}
