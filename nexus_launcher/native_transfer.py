"""Optional Rust transfer verification; transport and staging ownership stay in Python.

Only absence of the extension permits the compatibility implementation. A broken
or incompatible installed extension is an error, not a silent downgrade.
"""

import hashlib

MAX_FILE_BYTES = 1024 * 1024 * 1024


class _PythonTransferVerifier:
    def __init__(self, digest: str, expected_size: int | None = None):
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdefABCDEF" for c in digest):
            raise ValueError("Expected SHA-256 must contain exactly 64 hex digits")
        if expected_size is not None and not 0 <= expected_size <= MAX_FILE_BYTES:
            raise ValueError("Expected size exceeds the file limit")
        self._expected = bytes.fromhex(digest)
        self._size = expected_size
        self._received = 0
        self._hasher = hashlib.sha256()

    @property
    def received(self) -> int:
        return self._received

    def update(self, block: bytes) -> None:
        if self._hasher is None:
            raise ValueError("Transfer verifier is closed")
        size = self._received + len(block)
        limit = self._size if self._size is not None else MAX_FILE_BYTES
        if size > limit:
            self._hasher = None
            raise ValueError("Transfer exceeds its byte limit")
        self._hasher.update(block)
        self._received = size

    def finish(self) -> int:
        if self._hasher is None:
            raise ValueError("Transfer verifier is closed")
        hasher, self._hasher = self._hasher, None
        if self._size is not None and self._received != self._size:
            raise ValueError("Transfer size does not match expected size")
        if hasher.digest() != self._expected:
            raise ValueError("Transfer SHA-256 does not match expected digest")
        return self._received


try:
    import _nexus_launcher_core as _native
except ModuleNotFoundError as error:
    if error.name != "_nexus_launcher_core":
        raise
    TransferVerifier = _PythonTransferVerifier
    BACKEND = "python"
    _native = None
else:
    if _native.CORE_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS Rust core API")
    TransferVerifier = _native.TransferVerifier
    BACKEND = "rust"
