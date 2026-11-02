"""Adversarial fixtures only: no real credentials, sockets, Java or malware."""
from contextlib import nullcontext
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

from nexus_launcher.projects import ServerProfile
from nexus_launcher.secure_http import OriginRedirects
from nexus_launcher.server_controller import PterodactylServerController
from nexus_launcher.updater import ModpackUpdater, PackFile, PackRelease, fetch_manifest


class Response(io.BytesIO):
    status = 200
    def __init__(self, data):
        super().__init__(data)
        self.headers = {'Content-Length': str(len(data))}


class AdversarialProtectionTests(unittest.TestCase):
    def setUp(self):
        # An accidental live network path must fail the test, not reach a server.
        self.network = patch('socket.socket.connect', side_effect=AssertionError('Unexpected network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_zip_traversal_ads_and_windows_aliases_preserve_neighbour(self):
        paths = ['../neighbour.dat', '/neighbour.dat', 'C:/neighbour.dat',
                 'config/../../neighbour.dat', 'config\\..\\..\\neighbour.dat',
                 'config/a.json:payload.exe', 'config/a.exe.', 'config/CON.jar',
                 'config/a.exe ', 'mods/a.jar/../../neighbour.dat']
        for path in paths:
            with self.subTest(path=path), tempfile.TemporaryDirectory(prefix='nexus-adversarial-') as tmp:
                root = Path(tmp)
                neighbour = root / 'neighbour.dat'
                neighbour.write_bytes(b'not a real secret')
                archive = root / 'pack.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr('config/normal.json', '{}')
                    z.writestr(path, b'never executed')
                game = root / 'game'
                updater = ModpackUpdater(game, log=lambda _: None)
                with self.assertRaises(ValueError):
                    updater.apply(archive, PackRelease('1', '', hashlib.sha256(archive.read_bytes()).hexdigest()))
                self.assertEqual(neighbour.read_bytes(), b'not a real secret')
                self.assertFalse(game.exists())

    def test_manifest_size_bound(self):
        # Exceeds the actual read bound, not merely a claimed Content-Length.
        reply = Response(b' ' * (1024 * 1024 + 1))
        reply.headers = {}
        with patch('nexus_launcher.updater.open_https', return_value=reply):
            with self.assertRaises(ValueError):
                fetch_manifest('https://example.test/manifest')

    def test_escaped_duplicate_key_and_case_aliases(self):
        raw = b'{"version":"1","vers\\u0069on":"2"}'
        with patch('nexus_launcher.updater.open_https', return_value=Response(raw)):
            with self.assertRaises(ValueError):
                fetch_manifest('https://example.test/manifest')
        entry = {'path': 'mods/Example.jar', 'url': 'https://github.com/example/file',
                 'size': 1, 'sha256': 'a' * 64}
        payload = {'version': '1', 'files': [entry, {**entry, 'path': 'mods/example.jar'}]}
        with patch('nexus_launcher.updater.open_https', return_value=Response(json.dumps(payload).encode())):
            with self.assertRaises(ValueError):
                fetch_manifest('https://example.test/manifest')

    def test_wrong_hash_never_replaces_installed_mod_or_world(self):
        with tempfile.TemporaryDirectory(prefix='nexus-hash-refusal-') as tmp:
            root = Path(tmp)
            (root / 'mods').mkdir()
            (root / 'saves').mkdir()
            installed = root / 'mods/example.jar'
            world = root / 'saves/user.dat'
            installed.write_bytes(b'previous synthetic mod')
            world.write_bytes(b'previous synthetic world')
            entry = PackFile('a', 'Example', '1', 'mods/example.jar',
                'https://github.com/example/file', 4, hashlib.sha256(b'good').hexdigest())
            updater = ModpackUpdater(root, log=lambda _: None)
            with (patch('nexus_launcher.updater.open_https', side_effect=lambda *a, **k: Response(b'evil')),
                  patch('nexus_launcher.updater.time.sleep')):
                with self.assertRaises(ValueError):
                    updater._sync_files(PackRelease('1', '', '', files=(entry,)))
            self.assertEqual(installed.read_bytes(), b'previous synthetic mod')
            self.assertEqual(world.read_bytes(), b'previous synthetic world')

    def test_oversized_transfer_does_not_install(self):
        with tempfile.TemporaryDirectory(prefix='nexus-size-refusal-') as tmp:
            root = Path(tmp)
            entry = PackFile('a', 'Example', '1', 'mods/example.jar',
                'https://github.com/example/file', 1, hashlib.sha256(b'x').hexdigest())
            updater = ModpackUpdater(root, log=lambda _: None)
            with (patch('nexus_launcher.updater.open_https', side_effect=lambda *a, **k: Response(b'xx')),
                  patch('nexus_launcher.updater.time.sleep')):
                with self.assertRaises(ValueError):
                    updater._sync_files(PackRelease('1', '', '', files=(entry,)))
            self.assertFalse((root / 'mods/example.jar').exists())

    def test_credentialed_redirects_are_never_forwarded(self):
        policy = OriginRedirects({('https', 'mgr.bisquit.host', 443)})
        for header in ['Authorization', 'Cookie']:
            for destination in ['https://mgr.bisquit.host/other', 'https://attacker.example/']:
                with self.subTest(header=header, destination=destination):
                    request = urllib.request.Request('https://mgr.bisquit.host/api',
                        headers={header: 'synthetic-not-a-real-secret'})
                    with self.assertRaises(ValueError):
                        policy.redirect_request(request, None, 302, 'Found', {}, destination)

    def test_public_download_redirect_requires_allowlisted_origin(self):
        policy = OriginRedirects({('https', 'github.com', 443),
                                  ('https', 'release-assets.githubusercontent.com', 443)})
        request = urllib.request.Request('https://github.com/example/file')
        allowed = policy.redirect_request(request, None, 302, 'Found', {},
                                         'https://release-assets.githubusercontent.com/file')
        self.assertIsNotNone(allowed)
        for destination in ['http://github.com/file', 'https://github.com.attacker.example/file',
                            'https://attacker.example/file', 'https://github.com:444/file']:
            with self.subTest(destination=destination), self.assertRaises(ValueError):
                policy.redirect_request(request, None, 302, 'Found', {}, destination)

    def test_panel_origin_obfuscation_cannot_read_or_send_token(self):
        class NeverRead:
            def get_password(self, *args):
                raise AssertionError('Credential read for forged endpoint')
        profile = ServerProfile('test', 'Test', 'example.test', panel_server_id='0d2ad2ea')
        for panel in ['https://mgr.bisquit.host./', 'https://mgr.bisquit.host%2eattacker.example',
                      'https://mgr.bisquit.host@attacker.example', 'https://attacker.example@mgr.bisquit.host',
                      'https://mgr.bisquit.host/../api', 'https://mgr.bisquit.host//attacker.example',
                      'https://mgr.bisquit.host?next=https://attacker.example']:
            controller = PterodactylServerController(replace(profile, panel_url=panel),
                keyring_module=NeverRead(), opener=lambda *a, **k: self.fail('Unexpected HTTP'),
                authorization=lambda _: nullcontext())
            with self.subTest(panel=panel), self.assertRaises(ValueError):
                controller._request('/resources')

    def test_renamed_code_is_not_a_sandbox_or_malware_detection_claim(self):
        # A harmless marker disguised as a JAR illustrates the actual limitation:
        # path admission cannot inspect Java behaviour or guarantee safety.
        from nexus_launcher.server_pack_review import review
        profile = ServerProfile('test', 'Test', 'example.test', 'https://example.test/manifest')
        entry = PackFile('a', 'Example', '1', 'mods/renamed.jar',
                        'https://github.com/example/file', 1, 'a' * 64)
        report = review(profile, PackRelease('1', '', '', files=(entry,)))
        self.assertEqual(report.status, 'REVIEW_REQUIRED')
        self.assertIn('PLAYER_ISOLATION', {f.code for f in report.findings})


if __name__ == '__main__':
    unittest.main()
