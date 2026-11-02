"""Native UI tests with synthetic report/probes; no JVM, network or installation."""
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication
from nexus_launcher.preinstall_check import Check, Report
from nexus_launcher.nexus_platform.preinstall_dialog import PreinstallDialog

class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app=QApplication.instance() or QApplication([])
    def make(self,operation):
        self.dialog=PreinstallDialog(SimpleNamespace(name='Тестовая сборка · NeoForge'),Path('/fixture'),operation=operation)
        self.dialog.show();self.app.processEvents();return self.dialog
    def wait_idle(self):
        deadline=time.monotonic()+5
        while self.dialog.worker is not None and time.monotonic()<deadline:self.app.processEvents();time.sleep(.01)
        self.assertIsNone(self.dialog.worker)
    def tearDown(self):
        if hasattr(self,'dialog'):self.dialog.reject();self.wait_idle();self.dialog.deleteLater();self.app.processEvents()
    def test_explicit_start_result_and_manual_retry(self):
        calls=[]
        checks=tuple(Check(key,title,state,detail) for key,title,state,detail in [
          ('ram','RAM','warning','Доступно 3.2 ГБ. Для Java выбрано 6144 МБ. Память не резервируется.'),
          ('disk','Диск','unknown','Свободно 24.5 ГБ; размер полной установки не задан.'),
          ('java','Java','ok','Java 21 обнаружена.'),
          ('network','Связь','ok','DNS + TCP: 42 мс. Это не игровой пинг.'),
          ('fps','FPS','unknown','FPS не измерялся. Нужна установленная сборка и тестовая сцена.')])
        def operation(cancelled):calls.append(True);return Report(checks,time.time())
        d=self.make(operation);self.assertEqual(calls,[])
        metrics=QFontMetrics(d.start_button.font());self.assertTrue(metrics.inFontUcs4(ord('П')));self.assertTrue(metrics.inFontUcs4(ord('J')))
        d.start_button.click();d.start_button.click();self.wait_idle();self.assertEqual(len(calls),1)
        self.assertIn('ОБРАТИТЕ ВНИМАНИЕ',d.labels[0].text());self.assertIn('НЕ ПОДТВЕРЖДЕНО',d.labels[4].text())
        self.assertTrue(d.start_button.isEnabled());self.assertFalse(d.progress.isVisible())
        if path:=os.environ.get('NEXUS_PREINSTALL_SCREENSHOT'):d.grab().save(path)
        d.resize(520,620);self.app.processEvents()
        if path:=os.environ.get('NEXUS_PREINSTALL_NARROW_SCREENSHOT'):d.grab().save(path)
        d.start_button.click();self.wait_idle();self.assertEqual(len(calls),2)
    def test_failure_is_sanitized(self):
        def operation(cancelled):raise RuntimeError('SECRET fixture password or local path')
        d=self.make(operation);d.start_button.click();self.wait_idle()
        self.assertNotIn('SECRET',d.status.text());self.assertTrue(all('SECRET' not in x.text() for x in d.labels));self.assertTrue(d.start_button.isEnabled())
    def test_closing_waits_for_owned_worker_without_termination(self):
        entered=threading.Event()
        def operation(cancelled):
            entered.set()
            while not cancelled():time.sleep(.005)
            return Report((),time.time(),True)
        d=self.make(operation);d.start_button.click();self.assertTrue(entered.wait(2));d.reject()
        self.assertIsNotNone(d.worker);self.assertTrue(d.worker.cancel.is_set());self.wait_idle();self.assertFalse(d.isVisible())

if __name__=='__main__':unittest.main()
