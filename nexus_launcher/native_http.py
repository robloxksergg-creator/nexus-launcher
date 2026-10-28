"""Public pack downloads via the optional Rust client; no account credentials.

The narrow urllib-shaped adapter preserves updater injection points and leaves
staging/apply ownership in Python during migration. No fallback after network or
native errors. Only absence of a native HTTP implementation selects urllib.
"""

import threading
from email.message import Message

from nexus_launcher.native_transfer import _native as _core
from nexus_launcher.secure_http import open_https as _python_open_https, origin

_client = None
_client_lock = threading.Lock()
_MAX_READ = 1024 * 1024
_MAX_BUFFERED_READ = 4 * 1024 * 1024 + 1


class _Response:
    def __init__(self, inner):
        self._inner = inner
        self.status = inner.status
        self.headers = Message()
        for name, value in inner.headers:
            self.headers[name] = value

    def read1(self, size=_MAX_READ):
        if not isinstance(size, int) or not 0 <= size <= _MAX_READ:
            raise ValueError("Read limit must be between 0 and 1 MiB")
        return self._inner.read1(size)

    def read(self, size=_MAX_READ):
        # urllib read(n) fills until n bytes or EOF; a network chunk is not a
        # complete JSON manifest. Keep buffering bounded, including a limit+1 probe.
        if not isinstance(size, int) or not 0 <= size <= _MAX_BUFFERED_READ:
            raise ValueError("Buffered read exceeds its byte limit")
        chunks = []
        remaining = size
        while remaining:
            block = self.read1(min(remaining, _MAX_READ))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        return b"".join(chunks)

    def getcode(self):
        return self.status

    def geturl(self):
        return self._inner.geturl()

    def close(self):
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def open_https(request, timeout, *, allowed_hosts=None):
    initial = origin(request.full_url)
    if request.get_method() != "GET" or request.data is not None:
        raise ValueError("Native pack transport accepts GET without a body only")
    headers = request.header_items()
    if any(name.lower() not in {"user-agent", "accept", "range"} for name, _ in headers):
        raise ValueError("Only public pack-download headers are allowed")
    if _core is None or not hasattr(_core, "HTTP_API_VERSION"):
        return _python_open_https(request, timeout, allowed_hosts=allowed_hosts)
    if _core.HTTP_API_VERSION != 1:
        raise ImportError("Incompatible NEXUS native HTTP API")
    global _client
    with _client_lock:
        if _client is None:
            _client = _core.DownloadClient()
        client = _client
    hosts = [initial[1]] if allowed_hosts is None else list(allowed_hosts)
    return _Response(client.open(request.full_url, hosts, headers, timeout))
