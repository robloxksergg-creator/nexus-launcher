"""Pure entrypoint tests; no Qt, Keychain, account or game execution."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from nexus_launcher import macos_main


class MacEntrypointTests(unittest.TestCase):
    def test_native_apple_silicon_keeps_persistent_data(self):
        home = Path.home()
        with patch.object(macos_main.sys, 'platform', 'darwin'), \
             patch.object(macos_main.platform, 'machine', return_value='arm64'), \
             patch.object(macos_main.os, 'geteuid', return_value=1000, create=True), \
             patch.object(Path, 'home', return_value=home), \
             patch.dict(os.environ, {}, clear=True):
            root = macos_main.configure_environment()
            self.assertEqual(root, home / 'Library' / 'Application Support' / 'NEXUS Launcher')
            self.assertEqual(os.environ['NEXUS_PORTABLE_DATA'], str(root))
            self.assertEqual(os.environ['NEXUS_UI_2'], '1')
            self.assertEqual(os.environ['NEXUS_DISABLE_SELF_UPDATE'], '1')
            self.assertNotIn('QTWEBENGINE_DISABLE_SANDBOX', os.environ)

    def test_wrong_platform_or_intel_is_refused_before_changes(self):
        for system, machine in [('win32', 'ARM64'), ('linux', 'aarch64'), ('darwin', 'x86_64')]:
            with self.subTest(system=system, machine=machine), \
                 patch.object(macos_main.sys, 'platform', system), \
                 patch.object(macos_main.platform, 'machine', return_value=machine), \
                 patch.dict(os.environ, {}, clear=True):
                with self.assertRaises(RuntimeError):
                    macos_main.configure_environment()
                self.assertNotIn('NEXUS_PORTABLE_DATA', os.environ)

    def test_root_is_refused(self):
        with patch.object(macos_main.sys, 'platform', 'darwin'), \
             patch.object(macos_main.platform, 'machine', return_value='arm64'), \
             patch.object(macos_main.os, 'geteuid', return_value=0, create=True):
            with self.assertRaises(RuntimeError):
                macos_main.configure_environment()


if __name__ == '__main__':
    unittest.main()
