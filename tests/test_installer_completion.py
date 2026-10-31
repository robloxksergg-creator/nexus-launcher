"""Offline presentation and per-user shortcut tests. No launcher is executed."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from nexus_launcher.installer_completion import CompletionWindow
import runpy
installation_fixture = runpy.run_path(str(Path(__file__).with_name('test_online_installation.py')))
from nexus_launcher.online_installation import installation_details


class CompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_real_fixture_details_and_explicit_actions(self):
        fixture = installation_fixture['OnlineInstallationTests']()
        fixture.setUp()
        try:
            target = fixture.run_install()
            details = installation_details(target, keys=fixture.transport.keys)
            window = CompletionWindow(details)
            self.assertIn('99.0.0', window.version.text())
            self.assertNotIn('stable', window.version.text())
            self.assertEqual(window.location.text(), str(target.parent))
            self.assertTrue(window.launch_check.isChecked())
            self.assertFalse(window.shortcut_check.isChecked())
            if os.environ.get('NEXUS_COMPLETION_SCREENSHOT'):
                window.setWindowTitle('Предпросмотр — синтетический тестовый пакет, не реальная установка')
                window.show()
                self.app.processEvents()
                self.assertTrue(window.grab().save(os.environ['NEXUS_COMPLETION_SCREENSHOT']))
            actions = []
            window.finish_requested.connect(lambda launch, shortcut: actions.append((launch, shortcut)))
            window.launch_check.setChecked(False)
            window.shortcut_check.setChecked(True)
            window.done.click()
            self.assertEqual(actions, [(False, True)])
            window.set_busy(True)
            self.assertFalse(window.launch.isEnabled())
            window.close()
        finally:
            fixture.doCleanups()

    @unittest.skipUnless(os.name == 'nt', 'Windows ShellLink only')
    def test_shortcut_creation_preserves_existing_items(self):
        from nexus_launcher.windows_shortcut import create_shortcut
        with tempfile.TemporaryDirectory(prefix='nexus-shortcut-test-') as temporary:
            directory = Path(temporary)
            target = directory / 'NEXUS.exe'
            target.write_bytes(b'SYNTHETIC NOT EXECUTABLE')
            existing = directory / 'NEXUS Launcher.lnk'
            existing.write_bytes(b'PRESERVE USER SHORTCUT')
            created = create_shortcut(target, directory)
            self.assertNotEqual(created, existing)
            self.assertEqual(existing.read_bytes(), b'PRESERVE USER SHORTCUT')
            self.assertEqual(created.read_bytes()[:4], b'L\x00\x00\x00')
            self.assertFalse(list(directory.glob('.nexus-shortcut-*')))


if __name__ == '__main__':
    unittest.main()
