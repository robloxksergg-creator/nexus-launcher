"""Entrypoint policy tests; do not import Qt, start the app or contact services."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from nexus_launcher import linux_main


class LinuxEntrypointTests(unittest.TestCase):
    home = Path.home()

    def configure(self, env):
        with patch.object(linux_main.sys, 'platform', 'linux'), \
             patch.object(linux_main.os, 'geteuid', return_value=1000, create=True), \
             patch.dict(os.environ, env, clear=True), \
             patch.object(Path, 'home', return_value=self.home):
            root = linux_main.configure_environment()
            return root, dict(os.environ)

    def test_default_storage_is_persistent_and_updates_are_disabled(self):
        root, env = self.configure({})
        self.assertEqual(root, Path.home() / '.local' / 'share' / 'nexus-launcher')
        self.assertEqual(env['NEXUS_PORTABLE_DATA'], str(root))
        self.assertEqual(env['NEXUS_UI_2'], '1')
        self.assertEqual(env['NEXUS_DISABLE_SELF_UPDATE'], '1')

    def test_absolute_xdg_root_is_used(self):
        base = str(Path.home() / 'custom-data')
        root, env = self.configure({'XDG_DATA_HOME': base})
        self.assertEqual(root, Path(base) / 'nexus-launcher')
        self.assertEqual(env['XDG_DATA_HOME'], base)

    def test_relative_xdg_is_not_relative_to_install_folder(self):
        root, env = self.configure({'XDG_DATA_HOME': 'relative'})
        self.assertEqual(root, Path.home() / '.local' / 'share' / 'nexus-launcher')
        self.assertTrue(Path(env['XDG_DATA_HOME']).is_absolute())

    def test_rejects_windows_before_touching_environment(self):
        with patch.object(linux_main.sys, 'platform', 'win32'), patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                linux_main.configure_environment()
            self.assertNotIn('NEXUS_PORTABLE_DATA', os.environ)

    def test_rejects_root_without_disabling_chromium_sandbox(self):
        with patch.object(linux_main.sys, 'platform', 'linux'), \
             patch.object(linux_main.os, 'geteuid', return_value=0, create=True), \
             patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                linux_main.configure_environment()
            self.assertNotIn('QTWEBENGINE_DISABLE_SANDBOX', os.environ)


if __name__ == '__main__':
    unittest.main()
