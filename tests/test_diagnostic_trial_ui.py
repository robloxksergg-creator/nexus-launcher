"""Confirmation is exercised with Qt buttons, on a disposable personal pack."""
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from nexus_launcher.diagnostic_trial import DiagnosticTrials
from nexus_launcher.nexus_platform.instance_diagnostics_dialog import InstanceDiagnosticsDialog, TrialReviewDialog
from nexus_launcher.user_instances import InstanceService, InstalledMod


class TrialUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nexus-trial-ui-')
        self.addCleanup(self.temp.cleanup)
        self.service=InstanceService(Path(self.temp.name)/'instances')
        self.original=self.service.create('Тестовая сборка','1.21.1','fabric','0.16.10')
        self.root=self.service.path_for(self.original.id)
        jar=self.root/'mods/example.jar'
        with zipfile.ZipFile(jar,'w') as z:z.writestr('fabric.mod.json',json.dumps({'id':'example','depends':{'library_missing':'*'}}))
        self.original.installed_mods=[InstalledMod('local:example','v1','Example','example.jar',hashlib.sha512(jar.read_bytes()).hexdigest())]
        self.service.save(self.original)
        self.before={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.dialog=InstanceDiagnosticsDialog(self.root,'fabric','Тестовая сборка',trials=DiagnosticTrials(self.service,self.original.id,nullcontext))
        self.dialog.show();self.dialog.start_scan();self.wait_idle()
        self.assertTrue(self.dialog.prepare_trial.isEnabled())

    def tearDown(self):
        self.dialog.close();self.wait_idle()

    def wait_idle(self):
        deadline=time.monotonic()+20
        while self.dialog.worker is not None and time.monotonic()<deadline:QTest.qWait(20)
        self.assertIsNone(self.dialog.worker)

    def respond(self, accept, change_source=False):
        def click():
            active=QApplication.activeModalWidget()
            if not isinstance(active,TrialReviewDialog):
                QTimer.singleShot(20,click)
                return
            if change_source:(self.root/'config/changed.cfg').write_bytes(b'changed after confirmation preview')
            if accept and os.environ.get('NEXUS_TRIAL_REVIEW_SCREENSHOT'):
                QTest.qWait(100)
                self.assertTrue(active.grab().save(os.environ['NEXUS_TRIAL_REVIEW_SCREENSHOT']))
            (active.confirm_button if accept else active.cancel_button).click()
        QTimer.singleShot(0,click)

    def test_cancel_confirmation_leaves_no_copy(self):
        self.respond(False);self.dialog.prepare_trial.click();self.wait_idle()
        self.assertIsNone(self.dialog.trial_result)
        self.assertEqual([x.id for x in self.service.list()],[self.original.id])
        self.assertFalse((self.service.root/'.diagnostic-staging').exists())

    def test_confirm_creates_copy_and_navigation_does_not_launch(self):
        self.respond(True);self.dialog.prepare_trial.click();self.wait_idle()
        result=self.dialog.trial_result
        self.assertIsNotNone(result)
        self.assertTrue(self.dialog.open_trial.isEnabled())
        target=self.service.path_for(result.trial_id)
        self.assertTrue((target/'disabled_mods/example.jar').exists())
        self.assertEqual(self.before,{p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        if os.environ.get('NEXUS_TRIAL_RESULT_SCREENSHOT'):
            QTest.qWait(100)
            self.assertTrue(self.dialog.grab().save(os.environ['NEXUS_TRIAL_RESULT_SCREENSHOT']))
        self.dialog.open_trial.click()
        self.assertEqual(self.dialog.selected_instance_id,result.trial_id)
        self.assertFalse(self.dialog.isVisible())
        self.dialog.show()
        self.dialog.open_original.click()
        self.assertEqual(self.dialog.selected_instance_id,self.original.id)
        self.assertFalse(self.dialog.isVisible())

    def test_changed_source_after_preview_is_refused(self):
        self.respond(True,change_source=True);self.dialog.prepare_trial.click();self.wait_idle()
        self.assertIsNone(self.dialog.trial_result)
        self.assertIn('изменилась',self.dialog.status.text())
        self.assertTrue(self.dialog.scan.isEnabled())
        self.assertEqual({x.id for x in self.service.list()},{self.original.id})


if __name__=='__main__':
    unittest.main()
