"""Native presentation checks on owned fixtures, without games or network."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from nexus_launcher.instance_diagnostics import scan_instance
from nexus_launcher.nexus_platform.diagnostic_widgets import DiagnosticEntryCard
from nexus_launcher.nexus_platform.instance_diagnostics_dialog import InstanceDiagnosticsDialog
from nexus_launcher.nexus_platform.pages import ModsPage
from nexus_launcher.nexus_platform.presentation_style import stylesheet
from nexus_launcher.nexus_platform.theme_tokens import TOKENS


class WorkspaceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_entry_action_and_managed_scope(self):
        card = DiagnosticEntryCard(managed=True)
        calls = []
        card.requested.connect(lambda: calls.append(True))
        card.show()
        QTest.mouseClick(card.open_button, Qt.MouseButton.LeftButton)
        self.assertEqual(calls, [True])
        self.assertTrue(card.open_button.isEnabled())
        card.close()

    def test_managed_mods_counts_filter_and_empty_state(self):
        with tempfile.TemporaryDirectory(prefix='nexus-workspace-') as temp:
            root = Path(temp)
            (root/'mods').mkdir();(root/'disabled_mods').mkdir()
            (root/'mods/enabled.jar').write_bytes(b'fixture, not executed')
            (root/'disabled_mods/off.jar').write_bytes(b'fixture, not executed')
            page = ModsPage()
            page.setStyleSheet(stylesheet())
            page.resize(1000, 720)
            page.set_instance(root, {'off.jar'})
            self.assertIn('Включено: 1', page.inventory_status.text())
            self.assertIn('Отключено: 1', page.inventory_status.text())
            self.assertIn('Отключён', page.list.item(1).text())
            page.search.setText('off.jar')
            self.assertTrue(page.list.item(0).isHidden())
            page.set_instance(root, {'off.jar'})
            self.assertTrue(page.list.item(0).isHidden())
            page.search.clear()
            self.assertFalse(page.list.item(0).isHidden())
            signals = []
            page.diagnostics_requested.connect(lambda: signals.append(True))
            page.show();QTest.qWait(100)
            self.assertEqual(page.grab().toImage().pixelColor(5, 5).name(), TOKENS['background'])
            page.diagnostics_card.open_button.click()
            self.assertEqual(signals, [True])
            if os.environ.get('NEXUS_MODS_WORKSPACE_SCREENSHOT'):
                self.assertTrue(page.grab().save(os.environ['NEXUS_MODS_WORKSPACE_SCREENSHOT']))
            page.set_instance(root/'absent')
            self.assertEqual(page.list.count(), 0)
            self.assertIn('Модов пока нет', page.inventory_status.text())
            page.close()

    def test_nested_candidates_link_to_their_evidence(self):
        with tempfile.TemporaryDirectory(prefix='nexus-nested-ui-') as temp:
            root = Path(temp);(root/'mods').mkdir()
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, 'w') as archive:
                archive.writestr('fabric.mod.json', json.dumps({'schemaVersion':1,'id':'library','version':'2'}))
            with zipfile.ZipFile(root/'mods/example.jar', 'w') as archive:
                archive.writestr('fabric.mod.json', json.dumps({'schemaVersion':1,'id':'example','version':'1','jars':[{'file':'libs/library.jar'}]}))
                archive.writestr('libs/library.jar', payload.getvalue())
            dialog = InstanceDiagnosticsDialog(root, 'fabric', 'Вложенные библиотеки')
            dialog.show_report(scan_instance(root, 'fabric'))
            dialog.show();dialog.tabs.setCurrentIndex(2);QTest.qWait(100)
            self.assertEqual(dialog.nested_tree.topLevelItemCount(), 1)
            self.assertEqual(dialog.nested_tree.topLevelItem(0).text(0), 'Кандидат')
            self.assertEqual(dialog.nested_tree.topLevelItem(0).text(2), 'library@2')
            self.assertTrue(dialog.nested_source.isEnabled())
            if os.environ.get('NEXUS_NESTED_WORKSPACE_SCREENSHOT'):
                self.assertTrue(dialog.grab().save(os.environ['NEXUS_NESTED_WORKSPACE_SCREENSHOT']))
            dialog.nested_source.click()
            self.assertEqual(dialog.tabs.currentIndex(), 0)
            self.assertIn('example.jar ! libs/library.jar', dialog.evidence.toPlainText())
            dialog.show_report(scan_instance(root/'mods', 'fabric'))
            self.assertEqual(dialog.nested_tree.topLevelItemCount(), 0)
            self.assertFalse(dialog.nested_source.isEnabled())
            dialog.close()


if __name__ == '__main__':
    unittest.main()
