"""Real loopback sockets only: truncated HTTP body, Range resume and full hash."""
import hashlib
import io
import socket
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nexus_launcher.resumable_download import receive


def test_real_connection_drop_recovers_with_exact_bytes():
    body = bytes(range(256)) * 16384
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            offset = int((self.headers.get('Range') or 'bytes=0-')[6:-1])
            calls.append(offset)
            self.send_response(206 if offset else 200)
            self.send_header('Content-Length', str(len(body) - offset))
            if offset: self.send_header('Content-Range', f'bytes {offset}-{len(body)-1}/{len(body)}')
            self.end_headers()
            if len(calls) == 1:
                self.wfile.write(body[:1048576])
                self.wfile.flush()
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
            else:
                self.wfile.write(body[offset:])
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    output, progress = io.BytesIO(), []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def opened(offset):
        request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/synthetic')
        if offset: request.add_header('Range', f'bytes={offset}-')
        return opener.open(request, timeout=3)
    try:
        assert receive(output, opened, size=len(body), limit=len(body),
                       progress=lambda done, total: progress.append(done), retry_delay=0, timeout=10) == len(body)
        assert hashlib.sha256(output.getvalue()).digest() == hashlib.sha256(body).digest()
        assert calls == [0, 1048576]
        assert progress == sorted(progress)
    finally:
        server.shutdown()
        server.server_close()
        worker.join(3)
