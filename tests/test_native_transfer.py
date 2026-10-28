"""Shared contract tests for the Rust extension and Python compatibility path."""

import hashlib
import io
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from nexus_launcher import native_transfer
from nexus_launcher.updater import ModpackUpdater, PackFile


class VerifierContract:
    verifier_type = None

    def make(self, data=b"abc", size=3):
        return self.verifier_type(hashlib.sha256(data).hexdigest(), size)

    def test_chunking_and_success_is_terminal(self):
        for chunks in [(b"abc",), (b"a", b"", b"bc")]:
            with self.subTest(chunks=chunks):
                verifier = self.make()
                for block in chunks:
                    verifier.update(block)
                self.assertEqual(verifier.received, 3)
                self.assertEqual(verifier.finish(), 3)
                with self.assertRaises(ValueError):
                    verifier.finish()
                with self.assertRaises(ValueError):
                    verifier.update(b"")

    def test_empty_explicit_zero_and_unknown_size(self):
        self.assertEqual(self.make(b"", 0).finish(), 0)
        verifier = self.make(size=None)
        verifier.update(b"abc")
        self.assertEqual(verifier.finish(), 3)

    def test_invalid_digest_and_oversized_configuration(self):
        for digest in ("", "abc", "g" * 64, "é" * 32, "0" * 63 + " "):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                self.verifier_type(digest, None)
        with self.assertRaises(ValueError):
            self.make(size=native_transfer.MAX_FILE_BYTES + 1)

    def test_uppercase_digest(self):
        verifier = self.verifier_type(hashlib.sha256(b"abc").hexdigest().upper(), 3)
        verifier.update(b"abc")
        self.assertEqual(verifier.finish(), 3)

    def test_overflow_is_terminal_and_does_not_accept_chunk(self):
        verifier = self.make()
        verifier.update(b"a")
        with self.assertRaises(ValueError):
            verifier.update(b"bcd")
        self.assertEqual(verifier.received, 1)
        with self.assertRaises(ValueError):
            verifier.update(b"bc")
        with self.assertRaises(ValueError):
            verifier.finish()

    def test_short_read_is_terminal(self):
        verifier = self.make()
        verifier.update(b"ab")
        with self.assertRaises(ValueError):
            verifier.finish()
        with self.assertRaises(ValueError):
            verifier.update(b"c")

    def test_corrupt_read_is_terminal(self):
        verifier = self.make()
        verifier.update(b"abd")
        with self.assertRaises(ValueError):
            verifier.finish()
        with self.assertRaises(ValueError):
            verifier.finish()


class PythonVerifierTests(VerifierContract, unittest.TestCase):
    verifier_type = native_transfer._PythonTransferVerifier


class BackendSelectionTests(unittest.TestCase):
    def test_incompatible_installed_extension_does_not_downgrade(self):
        fake = types.ModuleType("_nexus_launcher_core")
        fake.CORE_API_VERSION = 999
        with patch.dict(sys.modules, {"_nexus_launcher_core": fake}):
            with self.assertRaises(ImportError):
                runpy.run_path(native_transfer.__file__)

    def test_broken_installed_extension_does_not_downgrade(self):
        import builtins
        original_import = builtins.__import__

        def importing(name, *args, **kwargs):
            if name == "_nexus_launcher_core":
                raise ImportError("DLL load failed")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=importing):
            with self.assertRaisesRegex(ImportError, "DLL load failed"):
                runpy.run_path(native_transfer.__file__)


@unittest.skipUnless(native_transfer.BACKEND == "rust", "Rust extension not installed")
class RustVerifierTests(VerifierContract, unittest.TestCase):
    verifier_type = native_transfer.TransferVerifier


class Response(io.BytesIO):
    def __init__(self, data, status=200, content_range=""):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Range": content_range}


class UpdaterTransferTests(unittest.TestCase):
    def download(self, prefix, body, *, status=200, content_range="", expected=b"abc", size=3):
        # In-memory HTTP response only: no sockets, installed packs or game execution.
        with tempfile.TemporaryDirectory(prefix="nexus-transfer-test-") as directory:
            path = Path(directory) / "staged"
            path.write_bytes(prefix)
            entry = PackFile("test", "test", "1", "mods/test.jar", "https://example.invalid/test", size,
                             hashlib.sha256(expected).hexdigest())
            updater = ModpackUpdater(Path(directory) / "game", log=lambda _: None)
            transferred = [0]
            with patch("nexus_launcher.updater.DOWNLOAD_ATTEMPTS", 1), patch(
                "nexus_launcher.updater.open_https", return_value=Response(body, status, content_range)
            ) as transport:
                result = updater._download_file(entry, path, transferred, max(size, 3))
            request = transport.call_args.args[0]
            return result, transferred[0], path.read_bytes(), request.get_header("Range")

    def test_fresh_download(self):
        self.assertEqual(self.download(b"", b"abc"), (3, 3, b"abc", None))

    def test_resume_verifies_prefix_and_suffix(self):
        self.assertEqual(self.download(b"a", b"bc", status=206, content_range="bytes 1-2/3"),
                         (3, 3, b"abc", "bytes=1-"))

    def test_ignored_range_restarts_without_appending(self):
        self.assertEqual(self.download(b"x", b"abc"), (3, 3, b"abc", "bytes=1-"))

    def test_unknown_size_is_still_verified(self):
        self.assertEqual(self.download(b"", b"abc", size=0), (3, 3, b"abc", None))

    def test_corrupt_prefix_is_rejected(self):
        with self.assertRaises(ValueError):
            self.download(b"x", b"bc", status=206, content_range="bytes 1-2/3")

    def test_oversized_and_truncated_responses_are_rejected(self):
        for body in (b"ab", b"abcd"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.download(b"", body)

    def test_staged_file_is_independently_read_back(self):
        with patch("nexus_launcher.updater.sha256_file", return_value="0" * 64) as readback:
            with self.assertRaises(ValueError):
                self.download(b"", b"abc")
            readback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
