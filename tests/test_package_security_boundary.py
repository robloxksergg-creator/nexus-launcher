"""Synthetic pack attacks; no game execution or network requests."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from nexus_launcher.updater import (ModpackUpdater, PackFile, PackRelease,
    fetch_manifest, validate_pack_content_path)


class Reply(io.BytesIO):
    def __init__(self, raw):
        super().__init__(raw)
        self.headers = {'Content-Length': str(len(raw))}


class PackageBoundaryTests(unittest.TestCase):
    def file(self, path='mods/example.jar'):
        return PackFile('a', 'Example', '1', path,
                        'https://github.com/example/packs/file', 1, 'a' * 64)

    def payload(self):
        return {'version': '1', 'files': [dict(path='mods/example.jar',
            url='https://github.com/example/packs/file', size=1, sha256='a' * 64)]}

    def fetch(self, raw):
        with patch('nexus_launcher.updater.open_https', return_value=Reply(raw)):
            return fetch_manifest('https://example.test/manifest.json')

    def test_normal_pack_data_and_java_remain_supported(self):
        for path in ['mods/a.jar', 'config/a.json', 'kubejs/startup_scripts/a.js',
                     'resourcepacks/a.zip', 'libraries/a.jar', 'nexus-rc-version.txt']:
            with self.subTest(path=path):
                validate_pack_content_path(path)
        self.assertEqual(len(self.fetch(json.dumps(self.payload()).encode()).files), 1)

    def test_os_executables_and_shortcuts_blocked(self):
        for name in ['a.EXE', 'a.dll', 'a.so', 'liba.so.2', 'a.dylib', 'a.ps1',
                     'a.bat', 'a.cmd', 'a.sh', 'a.desktop', 'a.lnk', 'a.url', 'a.reg']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_pack_content_path('config/' + name)

    def test_paths_cannot_escape_or_turn_metadata_file_into_directory(self):
        for path in ['../data/token', 'config/../../token', 'config/CON.json',
                     'nexus-rc-version.txt/child.json', 'accounts/session.json']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_pack_content_path(path)

    def test_duplicate_json_keys_rejected_at_every_level(self):
        for raw in [b'{"version":"1","version":"2"}',
                    b'{"files":[{"path":"mods/a.jar","path":"config/a.exe"}]}',
                    b'[]']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.fetch(raw)

    def test_manifest_cannot_deliver_executable_or_credential_url(self):
        for change in [{'path': 'config/a.exe'},
                       {'url': 'https://user:secret@github.com/file'},
                       {'url': 'https://github.com:444/file'},
                       {'url': 'https://github.com/file#fragment'}]:
            payload = self.payload()
            payload['files'][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.fetch(json.dumps(payload).encode())

    def test_direct_file_sync_refuses_before_state_write_or_download(self):
        with tempfile.TemporaryDirectory(prefix='nexus-pack-boundary-') as tmp:
            root = Path(tmp) / 'game'
            updater = ModpackUpdater(root)
            release = PackRelease('1', '', '', files=(self.file('config/a.exe'),))
            with (patch.object(updater, '_read_state', side_effect=AssertionError('Too late')),
                  patch.object(updater, '_download_file', side_effect=AssertionError('No download'))):
                with self.assertRaises(ValueError):
                    updater._sync_files(release)
            self.assertFalse(root.exists())

    def test_legacy_archive_refuses_before_game_write_and_preserves_other_data(self):
        with tempfile.TemporaryDirectory(prefix='nexus-archive-boundary-') as tmp:
            root = Path(tmp)
            other = root / 'other-player-token'
            other.write_bytes(b'synthetic unchanged sentinel')
            archive = root / 'pack.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('config/normal.json', '{}')
                z.writestr('config/payload.exe', b'synthetic data, never executed')
            game = root / 'game'
            updater = ModpackUpdater(game)
            release = PackRelease('1', 'https://github.com/example/pack.zip',
                                  hashlib.sha256(archive.read_bytes()).hexdigest())
            with patch('nexus_launcher.updater.apply_transaction', side_effect=AssertionError('No mutation')):
                with self.assertRaises(ValueError):
                    updater.apply(archive, release)
            self.assertFalse(game.exists())
            self.assertEqual(other.read_bytes(), b'synthetic unchanged sentinel')

    def test_valid_archive_installs_data_preserving_user_files(self):
        with tempfile.TemporaryDirectory(prefix='nexus-valid-pack-') as tmp:
            root = Path(tmp)
            game = root / 'game'
            (game / 'saves').mkdir(parents=True)
            sentinel = game / 'saves/user.dat'
            sentinel.write_bytes(b'synthetic user world')
            archive = root / 'pack.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('mods/sample.jar', b'synthetic bytes, not executable Java')
                z.writestr('config/sample.json', '{}')
            updater = ModpackUpdater(game, log=lambda _: None)
            updater.apply(archive, PackRelease('1', 'https://github.com/example/pack.zip',
                          hashlib.sha256(archive.read_bytes()).hexdigest()))
            self.assertEqual((game / 'mods/sample.jar').read_bytes(), b'synthetic bytes, not executable Java')
            self.assertEqual(sentinel.read_bytes(), b'synthetic user world')
            self.assertEqual(updater.installed_version, '1')


if __name__ == '__main__':
    unittest.main()
