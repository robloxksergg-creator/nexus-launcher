"""Transport adapter checks use fake responses and never contact the network."""

import types
import unittest
import urllib.request
from unittest.mock import Mock, patch

from nexus_launcher import native_http


class NativeHttpTests(unittest.TestCase):
    def setUp(self):
        self.response = Mock(status=206, headers=[("content-length", "2"), ("content-range", "bytes 1-2/3")])
        self.response.read1.return_value = b"bc"
        self.response.read1.side_effect = lambda size: b"bc" if size else b""
        self.response.geturl.return_value = "https://example.test/file"
        self.client = Mock()
        self.client.open.return_value = self.response
        self.core = types.SimpleNamespace(HTTP_API_VERSION=1, DownloadClient=Mock(return_value=self.client))

    def request(self, url="https://example.test/file", **kwargs):
        return urllib.request.Request(url, **kwargs)

    def test_reuses_client_and_preserves_streaming_contract(self):
        with patch.object(native_http, "_core", self.core), patch.object(native_http, "_client", None):
            for _ in range(2):
                with native_http.open_https(self.request(headers={"Range": "bytes=1-"}), 60,
                                            allowed_hosts={"example.test"}) as response:
                    self.assertEqual(response.status, 206)
                    self.assertEqual(response.getcode(), 206)
                    self.assertEqual(response.headers.get("Content-Length"), "2")
                    self.assertEqual(response.headers.get("Content-Range"), "bytes 1-2/3")
                    self.assertEqual(response.read1(10), b"bc")
                    self.assertEqual(response.geturl(), "https://example.test/file")
            self.core.DownloadClient.assert_called_once()
            self.assertEqual(self.response.close.call_count, 2)
            self.assertEqual(self.client.open.call_count, 2)
            self.assertEqual(self.client.open.call_args.args[1], ["example.test"])

    def test_only_absence_of_http_backend_uses_python(self):
        for core in (None, types.SimpleNamespace()):
            with patch.object(native_http, "_core", core), patch.object(native_http, "_python_open_https") as fallback:
                request = self.request()
                native_http.open_https(request, 60)
                fallback.assert_called_once_with(request, 60, allowed_hosts=None)

    def test_incompatible_backend_is_not_silently_downgraded(self):
        with patch.object(native_http, "_core", types.SimpleNamespace(HTTP_API_VERSION=2)), patch.object(
            native_http, "_python_open_https"
        ) as fallback:
            with self.assertRaises(ImportError):
                native_http.open_https(self.request(), 60)
            fallback.assert_not_called()

    def test_network_errors_are_not_silently_downgraded(self):
        self.client.open.side_effect = TimeoutError("HTTPS download timed out")
        with patch.object(native_http, "_core", self.core), patch.object(native_http, "_client", None), patch.object(
            native_http, "_python_open_https"
        ) as fallback:
            with self.assertRaises(TimeoutError):
                native_http.open_https(self.request(), 60)
            fallback.assert_not_called()

    def test_sensitive_headers_and_non_get_are_rejected_before_backend(self):
        requests = [self.request(headers={name: "secret"}) for name in
                    ("Authorization", "Cookie", "Proxy-Authorization", "Host")]
        requests += [self.request(data=b"body"), self.request(method="DELETE")]
        with patch.object(native_http, "_core", self.core):
            for request in requests:
                with self.subTest(request=request), self.assertRaises(ValueError):
                    native_http.open_https(request, 60)
            self.core.DownloadClient.assert_not_called()

    def test_invalid_origins_are_rejected_before_backend(self):
        with patch.object(native_http, "_core", self.core):
            for url in ("http://example.test/a", "https://user:secret@example.test/a", "https://example.test:444/a"):
                with self.subTest(url=url), self.assertRaises(ValueError):
                    native_http.open_https(self.request(url), 60)
            self.core.DownloadClient.assert_not_called()

    def test_reads_are_bounded_and_context_closes_on_failure(self):
        with patch.object(native_http, "_core", self.core), patch.object(native_http, "_client", None):
            with native_http.open_https(self.request(), 60) as response:
                for size in (-1, 4 * 1024 * 1024 + 2, "all"):
                    with self.subTest(size=size), self.assertRaises(ValueError):
                        response.read(size)
                self.assertEqual(response.read(0), b"")
            self.response.read1.assert_not_called()
            self.response.close.assert_called_once()

    def test_buffered_read_collects_fragmented_manifest_and_limit_probe(self):
        self.response.read1.side_effect = [b'{"ok":', b'true}', b'']
        with patch.object(native_http, "_core", self.core), patch.object(native_http, "_client", None):
            with native_http.open_https(self.request(), 60) as response:
                self.assertEqual(response.read(1024 * 1024 + 1), b'{"ok":true}')
            self.assertEqual(self.response.read1.call_count, 3)
            self.assertTrue(all(call.args[0] <= 1024 * 1024 for call in self.response.read1.call_args_list))

    def test_context_closes_when_consumer_raises(self):
        with patch.object(native_http, "_core", self.core), patch.object(native_http, "_client", None):
            with self.assertRaises(RuntimeError):
                with native_http.open_https(self.request(), 60):
                    raise RuntimeError("consumer failed")
            self.response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
