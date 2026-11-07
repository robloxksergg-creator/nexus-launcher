"""Frozen UI/module acceptance on synthetic values; no measurements or network."""
import time
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from nexus_launcher.preinstall_check import Check, Report
from nexus_launcher.nexus_platform.preinstall_dialog import PreinstallDialog


def check(parent, output):
    checks=tuple(Check(key,key,'unknown','Синтетическая проверка интерфейса. Показатели системы не измерялись.') for key in ('ram','disk','java','network','fps'))
    dialog=PreinstallDialog(SimpleNamespace(name='Проверка состава пакета — тестовые данные'),Path(output).parent,
        parent=parent,operation=lambda cancelled:Report(checks,time.time()))
    app=QApplication.instance()
    try:
        dialog.show();dialog.start()
        deadline=time.monotonic()+5
        while dialog.worker is not None and time.monotonic()<deadline:
            app.processEvents();time.sleep(.01)
        if dialog.worker is not None:raise TimeoutError('Packaged preparation UI did not finish')
        app.processEvents()
        result={'visible':dialog.isVisible(),'cards':len(dialog.labels),'processed':dialog.scan_badge.text(),'synthetic':True,'network_calls':0}
        assert result['visible'] and result['cards']==5 and result['processed']=='ОБРАБОТАНО 5/5'
        target=Path(output).with_name(Path(output).stem+'-preinstall.png')
        if not dialog.grab().save(str(target)):raise OSError('Could not capture packaged preparation UI')
        return result
    finally:
        dialog.reject()
        while dialog.worker is not None:
            app.processEvents();time.sleep(.01)
        dialog.deleteLater()
