"""Native Qt review with owned synthetic files; no game/account/network."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from nexus_launcher.nexus_platform.instance_diagnostics_dialog import InstanceDiagnosticsDialog


class DiagnosticsUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def fixture(self, root):
        (root/'mods').mkdir()
        with zipfile.ZipFile(root/'mods/example.jar','w') as z:
            z.writestr('fabric.mod.json',json.dumps({'id':'example','depends':{'fabric_api':'>=0.100','minecraft':'1.21.1'}}))
        (root/'crash-reports').mkdir()
        (root/'crash-reports/crash.txt').write_text('Mod ID: example\njava.lang.OutOfMemoryError: Java heap space --accessToken NEVER_SHOW_THIS\n',encoding='utf8')

    def wait(self, dialog):
        deadline=time.monotonic()+15
        while dialog.worker is not None and time.monotonic()<deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertIsNone(dialog.worker,'Worker did not finish')

    def test_report_selection_dependency_tree_refresh_and_narrow_window(self):
        with tempfile.TemporaryDirectory(prefix='nexus-diagnostics-ui-') as temp:
            root=Path(temp);self.fixture(root)
            dialog=InstanceDiagnosticsDialog(root,'fabric','Тестовая сборка')
            dialog.show();QTest.qWait(100)
            dialog.scan.click();self.wait(dialog)
            self.assertEqual(len(dialog.report.mods),1)
            self.assertEqual(dialog.dependencies.topLevelItemCount(),1)
            self.assertTrue(dialog.scan.isEnabled())
            self.assertEqual(dialog.summary_values[0].text(), '1')
            self.assertEqual(dialog.progress.maximum(), 1)
            self.assertEqual(dialog.progress.value(), 1)
            for row, finding in enumerate(dialog.report.findings):
                dialog.findings.setCurrentRow(row)
                self.assertNotIn('NEVER_SHOW_THIS',dialog.evidence.toPlainText())
                if finding.code=='MISSING_DEPENDENCY':
                    self.assertIn('fabric_api',dialog.evidence.toPlainText())
            dialog.findings.setCurrentRow(0)
            path=os.environ.get('NEXUS_DIAGNOSTICS_SCREENSHOT')
            if path:
                QTest.qWait(150)
                self.assertTrue(dialog.grab().save(path))
            dialog.resize(700,600);QTest.qWait(100)
            self.assertEqual(dialog.issues_splitter.orientation(), Qt.Orientation.Vertical)
            self.assertFalse(dialog.evidence.visibleRegion().isEmpty())
            self.assertGreaterEqual(dialog.findings.height(), 108)
            self.assertFalse(dialog.workspace_eyebrow.isVisible())
            if os.environ.get('NEXUS_DIAGNOSTICS_NARROW_SCREENSHOT'):
                self.assertTrue(dialog.grab().save(os.environ['NEXUS_DIAGNOSTICS_NARROW_SCREENSHOT']))
            self.assertFalse(dialog.scan.visibleRegion().isEmpty())
            self.assertFalse(dialog.close_button.visibleRegion().isEmpty())
            dialog.scan.click();self.wait(dialog)
            self.assertEqual(dialog.dependencies.topLevelItemCount(),1)
            dialog.close()

    def test_close_cancels_scan_without_destroying_running_thread(self):
        with tempfile.TemporaryDirectory(prefix='nexus-diagnostics-cancel-') as temp:
            root=Path(temp);self.fixture(root)
            dialog=InstanceDiagnosticsDialog(root,'fabric','Отмена')
            dialog.show();dialog.start_scan();dialog.reject()
            self.wait(dialog)
            self.assertFalse(dialog.isVisible())

    def test_unavailable_folder_can_retry_without_stuck_controls(self):
        with tempfile.TemporaryDirectory(prefix='nexus-diagnostics-failure-') as temp:
            root=Path(temp)/'absent'
            dialog=InstanceDiagnosticsDialog(root,'fabric','Ошибка чтения')
            dialog.start_scan();self.wait(dialog)
            self.assertIsNone(dialog.report)
            self.assertEqual(dialog.summary_values[0].text(), '—')
            self.assertEqual(dialog.progress.maximum(), 1)
            self.assertIn('Не удалось',dialog.status.text())
            root.mkdir();dialog.start_scan();self.wait(dialog)
            self.assertIsNotNone(dialog.report)
            dialog.close()


if __name__=='__main__':
    unittest.main()
