"""Native presentation of declared version conditions; synthetic local JARs."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import zipfile
from PySide6.QtWidgets import QApplication, QTabWidget
from PySide6.QtTest import QTest
from nexus_launcher.nexus_platform.instance_diagnostics_dialog import InstanceDiagnosticsDialog


class VersionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nexus-versions-ui-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'mods').mkdir()

    def jar(self,name,id,version,**fields):
        with zipfile.ZipFile(self.root/'mods'/name,'w') as z:
            z.writestr('fabric.mod.json',json.dumps({'schemaVersion':1,'id':id,'version':version,**fields}))

    def dialog(self):
        d=InstanceDiagnosticsDialog(self.root,'fabric','Тестовые версии')
        d.show();d.start_scan()
        deadline=time.monotonic()+15
        while d.worker is not None and time.monotonic()<deadline:
            self.app.processEvents();time.sleep(.01)
        self.assertIsNone(d.worker)
        self.assertIsNotNone(d.report)
        self.addCleanup(d.close)
        return d

    def test_numeric_mismatch_and_match_are_distinct_in_tree(self):
        self.jar('example.jar','example','1',depends={'library':'>=2','utility':'>=2 <3'})
        self.jar('library.jar','library','1.5')
        self.jar('utility.jar','utility','2.3')
        d=self.dialog()
        node=next(d.dependencies.topLevelItem(i) for i in range(d.dependencies.topLevelItemCount()) if d.dependencies.topLevelItem(i).text(0)=='example.jar')
        rows={node.child(i).text(0):node.child(i) for i in range(node.childCount())}
        self.assertEqual(rows['library'].text(2),'Не соответствует')
        self.assertEqual(rows['utility'].text(2),'Условие выполнено')
        self.assertIn('1.5',rows['library'].text(1))
        self.assertIn('VERSION_MISMATCH',{f.code for f in d.report.findings})
        d.findChild(QTabWidget).setCurrentIndex(1)
        node.setExpanded(True)
        QTest.qWait(100)
        if os.environ.get('NEXUS_VERSION_SCREENSHOT'):
            self.assertTrue(d.grab().save(os.environ['NEXUS_VERSION_SCREENSHOT']))
        d.resize(700,500);QTest.qWait(50)
        self.assertFalse(d.scan.visibleRegion().isEmpty())

    def test_unknown_format_does_not_display_condition_satisfied(self):
        self.jar('example.jar','example','1',depends={'library':'*'})
        self.jar('library.jar','library','dev-build')
        d=self.dialog()
        self.assertEqual(d.report.version_checks[0].status,'UNKNOWN')
        node=d.dependencies.topLevelItem(0)
        self.assertEqual(node.child(0).text(2),'Не проверено')
        self.assertIn('вне поддержанного',node.child(0).toolTip(2))


if __name__=='__main__':unittest.main()
