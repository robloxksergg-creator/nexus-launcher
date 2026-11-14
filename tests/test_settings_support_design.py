import os
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QSettings,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from nexus_launcher.nexus_platform.support_page import SupportPage
from tests.test_next_shell import candidate  # noqa: F401


def test_settings_bounded_panels_search_and_existing_controls(candidate):
    app,window,_=candidate
    workspace=window.settings_scroll;owner=window.settings_page
    window.resize(1900,950);window._navigate('settings','');app.processEvents()
    assert workspace.desk.width()<=1240
    assert owner.categories.count()==owner.panels.count()==10
    assert owner.general_values.findChildren(QLabel,'settingLine')
    workspace.search.setText('Java');app.processEvents()
    assert not owner.categories.item(2).isHidden()
    workspace.search.setText('no-such-setting');assert workspace.result.text()
    workspace.search.clear();owner.categories.setCurrentRow(5)
    observed=[];owner.settings_changed.connect(observed.append)
    owner.reduced_motion.click();assert 'reducedMotion' in observed[-1]
    owner.categories.setCurrentRow(0)
    captures=os.environ.get('NEXUS_SETTINGS_SUPPORT_CAPTURE')
    if captures:
        Path(captures).mkdir(parents=True,exist_ok=True);QTest.qWait(200);workspace.grab().save(str(Path(captures)/'settings.png'))


def test_support_responsive_counter_and_no_unauthenticated_send(candidate,monkeypatch,tmp_path):
    app,window,_=candidate
    monkeypatch.setattr('nexus_launcher.nexus_platform.support_page.QSettings',lambda *a:QSettings(str(tmp_path/'support.ini'),QSettings.IniFormat))
    page=SupportPage(SimpleNamespace(account_profile=None))
    page.resize(1200,850);page.show();app.processEvents()
    assert page.split.count()==2 and page.split.orientation()==Qt.Horizontal
    page.text.setPlainText('Тест');assert page.counter.text()=='4 / 4000 символов'
    page.send_button.click();assert not page.busy
    page.request('tickets');assert 'Войдите' in page.state.text()
    page.text.clear()
    captures=os.environ.get('NEXUS_SETTINGS_SUPPORT_CAPTURE')
    if captures:
        QTest.qWait(100);page.grab().save(str(Path(captures)/'support.png'))
    page.resize(720,850);app.processEvents()
    assert page.split.orientation()==Qt.Vertical
    page.close();assert not page.timer.isActive()
