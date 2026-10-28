//! Windows ancestor pinning and verified source-handle replacement.
//! Owning a pin does not establish containment or authorize writes by itself.

use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use sha2::{Digest, Sha256};
use std::io::{Read, Write};
use std::os::windows::fs::MetadataExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::{FromRawHandle, OwnedHandle};
use std::path::Path;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{GetLastError, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, FILE_ATTRIBUTE_DIRECTORY, FILE_ATTRIBUTE_REPARSE_POINT, FILE_ATTRIBUTE_TAG_INFO,
    FILE_FLAG_BACKUP_SEMANTICS, FILE_FLAG_OPEN_REPARSE_POINT, FILE_LIST_DIRECTORY,
    FILE_READ_ATTRIBUTES, FILE_SHARE_READ, FILE_SHARE_WRITE, FileAttributeTagInfo, GetDriveTypeW,
    GetFileInformationByHandleEx, OPEN_EXISTING,
};

fn win_error(code: u32) -> PyErr {
    // OSError's Windows constructor maps winerror to errno and keeps .winerror.
    PyOSError::new_err((
        0,
        std::io::Error::from_raw_os_error(code as i32).to_string(),
        Option::<String>::None,
        code,
    ))
}

fn io_error(error: std::io::Error) -> PyErr {
    match error.raw_os_error() {
        Some(code) => win_error(code as u32),
        None => PyOSError::new_err(error.to_string()),
    }
}

fn sha256_hex(digest: Sha256) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let bytes: [u8; 32] = digest.finalize().into();
    let mut text = String::with_capacity(64);
    for byte in bytes {
        text.push(HEX[(byte >> 4) as usize] as char);
        text.push(HEX[(byte & 15) as usize] as char);
    }
    text
}

fn duplicate_file(handle: usize) -> PyResult<std::fs::File> {
    use windows_sys::Win32::Foundation::{DUPLICATE_SAME_ACCESS, DuplicateHandle};
    use windows_sys::Win32::System::Threading::GetCurrentProcess;
    if handle == 0 || handle == usize::MAX || handle == usize::MAX - 1 {
        return Err(PyValueError::new_err("Expected an open file handle"));
    }
    let mut owned = std::ptr::null_mut();
    // SAFETY: the pseudo process handle requires no ownership; DuplicateHandle
    // validates the supplied value and writes a new, non-inheritable handle.
    // The original is never closed or consumed, even on failure.
    unsafe {
        let process = GetCurrentProcess();
        if DuplicateHandle(
            process,
            handle as _,
            process,
            &mut owned,
            0,
            0,
            DUPLICATE_SAME_ACCESS,
        ) == 0
        {
            return Err(win_error(GetLastError()));
        }
    }
    // SAFETY: successful DuplicateHandle transfers this unique owned handle.
    let file = unsafe { std::fs::File::from_raw_handle(owned) };
    let metadata = file.metadata().map_err(io_error)?;
    if !metadata.is_file() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(PyValueError::new_err("Copy requires regular file handles"));
    }
    Ok(file)
}

/// Caller owns the fresh temporary destination and keeps both original streams
/// open until return. Duplicates share offsets; no Python buffered IO may run
/// concurrently. This helper grants neither path containment nor atomicity.
#[pyfunction]
pub fn windows_copy_streams(
    py: Python<'_>,
    source_handle: usize,
    target_handle: usize,
    max_bytes: u64,
) -> PyResult<(u64, String)> {
    if source_handle == target_handle {
        return Err(PyValueError::new_err("Copy requires distinct streams"));
    }
    // Duplicate before releasing the GIL. Native code closes only its duplicates.
    let mut source = duplicate_file(source_handle)?;
    let mut target = duplicate_file(target_handle)?;
    py.detach(move || {
        let limit = max_bytes.min(1024 * 1024 * 1024);
        let deadline = Instant::now() + Duration::from_secs(300);
        let mut buffer = vec![0u8; 256 * 1024];
        let mut total = 0u64;
        let mut digest = Sha256::new();
        loop {
            if Instant::now() >= deadline {
                return Err(pyo3::exceptions::PyTimeoutError::new_err(
                    "File transfer exceeded its time budget",
                ));
            }
            // Probe at most one byte past the limit, never write that byte.
            let requested = (limit - total + 1).min(buffer.len() as u64) as usize;
            let count = source.read(&mut buffer[..requested]).map_err(io_error)?;
            if Instant::now() >= deadline {
                return Err(pyo3::exceptions::PyTimeoutError::new_err(
                    "File transfer exceeded its time budget",
                ));
            }
            if count == 0 {
                break;
            }
            total += count as u64;
            if total > limit {
                return Err(PyValueError::new_err("File exceeds byte limit"));
            }
            target.write_all(&buffer[..count]).map_err(io_error)?;
            digest.update(&buffer[..count]);
        }
        Ok((total, sha256_hex(digest)))
    })
}

/// No path-based reopen occurs between verification and replacement.
#[pyfunction]
pub fn windows_replace_file(
    py: Python<'_>,
    source: String,
    target: String,
    expected_sha256: Option<String>,
    max_bytes: u64,
) -> PyResult<()> {
    py.detach(move || {
        let source = local_path(&source)?;
        let target = local_path(&target)?;
        let parent = |path: &str| -> PyResult<String> {
            Path::new(path)
                .parent()
                .map(|p| p.to_string_lossy().into_owned())
                .filter(|p| !p.is_empty())
                .ok_or_else(|| PyValueError::new_err("File path requires a parent"))
        };
        let _source_pin = WindowsDirectoryPin::new(&parent(&source)?, false)?;
        let _target_pin = WindowsDirectoryPin::new(&parent(&target)?, false)?;
        let source_name = wide(&format!("\\\\?\\{source}"));
        // SAFETY: live UTF-16 buffer; READ + DELETE, sharing reads only. The leaf
        // cannot be written or renamed while this owned handle remains open.
        let handle = unsafe {
            CreateFileW(
                source_name.as_ptr(),
                0x80010000,
                FILE_SHARE_READ,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_FLAG_OPEN_REPARSE_POINT,
                std::ptr::null_mut(),
            )
        };
        if handle == INVALID_HANDLE_VALUE {
            // SAFETY: capture the failing call's thread-local error immediately.
            return Err(win_error(unsafe { GetLastError() }));
        }
        // SAFETY: the successful open transfers unique ownership to File.
        let mut file = unsafe { std::fs::File::from_raw_handle(handle) };
        let mut attributes = FILE_ATTRIBUTE_TAG_INFO {
            FileAttributes: 0,
            ReparseTag: 0,
        };
        // SAFETY: owned handle and correctly sized writable attributes buffer.
        if unsafe {
            GetFileInformationByHandleEx(
                file.as_raw_handle(),
                FileAttributeTagInfo,
                (&mut attributes as *mut FILE_ATTRIBUTE_TAG_INFO).cast(),
                std::mem::size_of::<FILE_ATTRIBUTE_TAG_INFO>() as u32,
            )
        } == 0
        {
            // SAFETY: read error before handle destruction.
            return Err(win_error(unsafe { GetLastError() }));
        }
        if attributes.FileAttributes & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_DIRECTORY)
            != 0
        {
            return Err(PyValueError::new_err("Source is a reparse point/directory"));
        }
        if let Some(expected) = expected_sha256 {
            let mut digest = Sha256::new();
            let mut buffer = vec![0u8; 1024 * 1024];
            let mut total = 0u64;
            let deadline = Instant::now() + Duration::from_secs(300);
            loop {
                if Instant::now() >= deadline {
                    return Err(pyo3::exceptions::PyTimeoutError::new_err(
                        "Staged file verification exceeded its time budget",
                    ));
                }
                let count = file
                    .read(&mut buffer)
                    .map_err(|error| match error.raw_os_error() {
                        Some(code) => win_error(code as u32),
                        None => PyOSError::new_err(error.to_string()),
                    })?;
                total += count as u64;
                if total > max_bytes.min(1024 * 1024 * 1024) {
                    return Err(PyValueError::new_err("Staged file exceeds byte limit"));
                }
                if count == 0 {
                    break;
                }
                digest.update(&buffer[..count]);
            }
            if sha256_hex(digest) != expected {
                return Err(PyValueError::new_err("Staged file hash mismatch"));
            }
        }
        use windows_sys::Win32::Storage::FileSystem::{
            FILE_RENAME_INFO, FileRenameInfo, SetFileInformationByHandle,
        };
        let name = wide(&format!("\\\\?\\{target}"));
        let offset = std::mem::offset_of!(FILE_RENAME_INFO, FileName);
        let length = offset + name.len() * 2;
        let length_u32 =
            u32::try_from(length).map_err(|_| PyValueError::new_err("Target path too long"))?;
        // u64 storage meets FILE_RENAME_INFO alignment on supported Windows targets.
        let mut storage = vec![
            0u64;
            length
                .max(std::mem::size_of::<FILE_RENAME_INFO>())
                .div_ceil(8)
        ];
        let info = storage.as_mut_ptr().cast::<FILE_RENAME_INFO>();
        // SAFETY: aligned zeroed storage includes the header and entire UTF-16 name;
        // length excludes the terminator, while the allocation includes it.
        unsafe {
            (*info).Anonymous.ReplaceIfExists = true;
            (*info).FileNameLength = ((name.len() - 1) * 2) as u32;
            std::ptr::copy_nonoverlapping(
                name.as_ptr(),
                storage.as_mut_ptr().cast::<u8>().add(offset).cast::<u16>(),
                name.len(),
            );
        }
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            // SAFETY: File owns the verified source handle; info lives through call.
            if unsafe {
                SetFileInformationByHandle(
                    file.as_raw_handle(),
                    FileRenameInfo,
                    info.cast(),
                    length_u32,
                )
            } != 0
            {
                return Ok(());
            }
            // SAFETY: capture before any sleep or destructor changes last error.
            let error = unsafe { GetLastError() };
            if !matches!(error, 5 | 32 | 33) || Instant::now() >= deadline {
                return Err(win_error(error));
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    })
}

fn local_path(text: &str) -> PyResult<String> {
    let path = text.replace('/', "\\");
    let bytes = path.as_bytes();
    if bytes.len() < 3 || !bytes[0].is_ascii_alphabetic() || bytes[1..3] != *b":\\" {
        return Err(PyValueError::new_err(
            "UNC/network/device/relative paths are not supported",
        ));
    }
    // The caller also runs checked_path; do not let direct native calls introduce
    // ambiguous extended-path spellings before opening any handles.
    let suffix = path[3..].strip_suffix('\\').unwrap_or(&path[3..]);
    if !suffix.is_empty() {
        for part in suffix.split('\\') {
            let base = part.split('.').next().unwrap_or("").to_ascii_uppercase();
            let device = matches!(base.as_str(), "CON" | "PRN" | "AUX" | "NUL")
                || ["COM", "LPT"].iter().any(|prefix| {
                    base.strip_prefix(*prefix)
                        .is_some_and(|n| n.chars().count() == 1 && "123456789¹²³".contains(n))
                });
            if part.is_empty()
                || matches!(part, "." | "..")
                || part.ends_with(['.', ' '])
                || part.chars().any(|c| c < ' ' || "<>:\"|?*".contains(c))
                || device
            {
                return Err(PyValueError::new_err("Invalid or ambiguous Windows path"));
            }
        }
    }
    Ok(path)
}

fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

#[pyclass(module = "_nexus_launcher_core")]
pub struct WindowsDirectoryPin {
    handles: Vec<OwnedHandle>,
}

impl Drop for WindowsDirectoryPin {
    fn drop(&mut self) {
        // Leaf first, including partial construction failure; never release twice.
        while self.handles.pop().is_some() {}
    }
}

#[pymethods]
impl WindowsDirectoryPin {
    #[new]
    #[pyo3(signature = (directory, create=false))]
    fn new(directory: &str, create: bool) -> PyResult<Self> {
        let directory = local_path(directory)?;
        let root = wide(&directory[..3]);
        // SAFETY: root is a live, NUL-terminated UTF-16 drive-root buffer.
        if unsafe { GetDriveTypeW(root.as_ptr()) } == 4 {
            return Err(PyValueError::new_err(
                "Mapped network drives are not supported",
            ));
        }
        let mut pin = Self {
            handles: Vec::new(),
        };
        let ancestors: Vec<_> = Path::new(&directory).ancestors().collect();
        for ancestor in ancestors.into_iter().rev() {
            if create && let Err(error) = std::fs::create_dir(ancestor) {
                // Unlike Path::is_dir(), this must not follow a junction while
                // deciding whether an existing directory is acceptable.
                let existing = std::fs::symlink_metadata(ancestor).ok();
                if existing
                    .as_ref()
                    .is_some_and(|m| m.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0)
                {
                    return Err(PyValueError::new_err("Unsafe reparse point in I/O path"));
                }
                if !existing.is_some_and(|m| m.is_dir()) {
                    return Err(match error.raw_os_error() {
                        Some(code) => win_error(code as u32),
                        None => PyOSError::new_err(error.to_string()),
                    });
                }
            }
            let name = wide(&format!("\\\\?\\{}", ancestor.display()));
            // SAFETY: UTF-16 lives through the call; no security/template pointers.
            // FILE_LIST_DIRECTORY is required: attribute-only handles do not pin.
            let handle = unsafe {
                CreateFileW(
                    name.as_ptr(),
                    FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    std::ptr::null(),
                    OPEN_EXISTING,
                    FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
                    std::ptr::null_mut(),
                )
            };
            if handle == INVALID_HANDLE_VALUE {
                // SAFETY: read thread-local error immediately after failed CreateFileW.
                return Err(win_error(unsafe { GetLastError() }));
            }
            // SAFETY: successful CreateFileW transfers a unique owned handle to us.
            pin.handles
                .push(unsafe { OwnedHandle::from_raw_handle(handle) });
            let mut attributes = FILE_ATTRIBUTE_TAG_INFO {
                FileAttributes: 0,
                ReparseTag: 0,
            };
            // SAFETY: handle is held by pin; writable buffer has the exact tag-info size.
            if unsafe {
                GetFileInformationByHandleEx(
                    handle,
                    FileAttributeTagInfo,
                    (&mut attributes as *mut FILE_ATTRIBUTE_TAG_INFO).cast(),
                    std::mem::size_of::<FILE_ATTRIBUTE_TAG_INFO>() as u32,
                )
            } == 0
            {
                // SAFETY: capture before OwnedHandle drop can change last-error state.
                return Err(win_error(unsafe { GetLastError() }));
            }
            if attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
                || attributes.FileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0
            {
                return Err(PyValueError::new_err(
                    "Unsafe reparse point/non-directory in I/O path",
                ));
            }
        }
        Ok(pin)
    }

    fn close(&mut self) {
        while self.handles.pop().is_some() {}
    }
}
