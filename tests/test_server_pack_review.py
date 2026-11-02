"""Synthetic metadata only; no package execution or security certification."""
import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

from nexus_launcher.projects import ServerProfile
from nexus_launcher.server_pack_review import review
from nexus_launcher.updater import PackFile, PackRelease


class ServerReviewTests(unittest.TestCase):
    def setUp(self):
        self.server = ServerProfile('sample', 'Sample', 'play.example.test',
            'https://example.test/manifest.json', '1.21.1', 'neoforge', '21.1.248')
        self.file = PackFile('one', 'Example', '1', 'mods/example.jar',
                             'https://example.test/example.jar', 20, 'a' * 64)
        self.release = PackRelease('1', '', '', minecraft_server=self.server.address,
            minecraft='1.21.1', loader='neoforge', loader_version='21.1.248', files=(self.file,))

    def codes(self, result):
        return {f.code for f in result.findings}

    def test_valid_metadata_is_not_safe_or_authorized(self):
        result = review(self.server, self.release)
        self.assertEqual(result.status, 'REVIEW_REQUIRED')
        self.assertEqual((result.files, result.declared_bytes), (1, 20))
        self.assertTrue({'JAVA_CODE', 'PLAYER_ISOLATION', 'TENANT_ISOLATION',
                         'PUBLISHER_IDENTITY'} <= self.codes(result))

    def test_no_manifest_blocks(self):
        self.assertEqual(review(self.server, None).status, 'BLOCKED')

    def test_minecraft_and_loader_conflicts_block(self):
        for field, value in [('minecraft', '1.20.1'), ('loader', 'forge'), ('loader_version', 'other')]:
            with self.subTest(field=field):
                self.assertEqual(review(self.server, replace(self.release, **{field: value})).status, 'BLOCKED')

    def test_missing_binding_remains_unknown(self):
        r = review(self.server, replace(self.release, minecraft=''))
        self.assertIn('MINECRAFT_BINDING', self.codes(r))
        self.assertEqual(r.status, 'REVIEW_REQUIRED')

    def test_address_alias_not_assumed_equal(self):
        self.assertIn('SERVER_BINDING', self.codes(review(self.server, replace(self.release, minecraft_server='192.0.2.1'))))

    def test_opaque_archive_not_certified(self):
        self.assertIn('OPAQUE_ARCHIVE', self.codes(review(self.server, replace(self.release, files=()))))

    def test_unsafe_and_duplicate_paths_block(self):
        for path in ['../token', 'mods/../token', 'accounts/token', 'mods/CON.jar', 'mods/a\\b.jar']:
            with self.subTest(path=path):
                r = review(self.server, replace(self.release, files=(replace(self.file, path=path),)))
                self.assertEqual(r.status, 'BLOCKED')
        duplicate = replace(self.file, path='mods/EXAMPLE.jar')
        self.assertEqual(review(self.server, replace(self.release, files=(self.file, duplicate))).status, 'BLOCKED')

    def test_integrity_fields_rejected(self):
        for changes in [{'size': -1}, {'size': True}, {'sha256': 'bad'}]:
            with self.subTest(changes=changes):
                r = review(self.server, replace(self.release, files=(replace(self.file, **changes),)))
                self.assertEqual(r.status, 'BLOCKED')

    def test_file_urls_cannot_embed_credentials_or_use_http(self):
        for url in ['http://example.test/a', 'https://user:secret@example.test/a', 'https://example.test:444/a']:
            with self.subTest(url=url):
                self.assertEqual(review(self.server, replace(self.release, files=(replace(self.file, url=url),))).status, 'BLOCKED')

    def test_native_block_and_js_review_are_not_malware_verdicts(self):
        for path, code, status in [('config/a.dll', 'NATIVE_CODE', 'BLOCKED'),
                                  ('kubejs/startup_scripts/a.js', 'SCRIPT_CODE', 'REVIEW_REQUIRED')]:
            with self.subTest(path=path):
                result = review(self.server, replace(self.release, files=(replace(self.file, path=path),)))
                self.assertEqual(result.status, status)
                self.assertIn(code, self.codes(result))

    def test_review_does_not_fetch_or_mutate(self):
        before = copy.deepcopy((self.server, self.release))
        with patch('nexus_launcher.updater.fetch_manifest', side_effect=AssertionError('No network')):
            review(self.server, self.release)
        self.assertEqual((self.server, self.release), before)


if __name__ == '__main__':
    unittest.main()
