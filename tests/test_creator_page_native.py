"""Actual offscreen Qt form + application model, synthetic account service."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QMessageBox,QWidget,QScrollArea
from nexus_launcher.creator_page_ui import CreatorPageDialog
from tests.test_creator_page_sync import PROFILE,Remote,fixture,content
from tests.test_creator_release_native import wait


def test_native_form_saves_submits_and_withdraws_same_application(tmp_path):
    app=QApplication.instance() or QApplication([])
    service,instance=fixture(tmp_path);remote=Remote()
    dialog=CreatorPageDialog(remote,PROFILE,service,instance.id)
    try:
        wait(app,lambda:not dialog.busy)
        for key,field in dialog.fields.items():
            if hasattr(field,'setPlainText'):field.setPlainText(content()[key])
            else:field.setText(content()[key])
        assert not dialog.submit.isEnabled()
        dialog.save.click();wait(app,lambda:not dialog.busy)
        saved_id=dialog.workspace.item['id']
        assert len(remote.items)==1 and not dialog.dirty
        dialog.rights.setChecked(True);assert dialog.submit.isEnabled()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            dialog.submit.click();wait(app,lambda:not dialog.busy)
        assert dialog.workspace.item['state']=='SUBMITTED'
        assert not dialog.save.isEnabled() and dialog.editor.isEnabled()
        assert all(field.isReadOnly() for field in dialog.fields.values())
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            dialog.withdraw.click();wait(app,lambda:not dialog.busy)
        assert dialog.editor.isEnabled() and dialog.workspace.item['id']==saved_id
    finally:dialog.dirty=False;dialog.close();dialog.deleteLater();app.processEvents()


def test_unknown_save_locks_writes_until_explicit_read_and_does_not_duplicate(tmp_path):
    app=QApplication.instance() or QApplication([])
    service,instance=fixture(tmp_path);remote=Remote()
    dialog=CreatorPageDialog(remote,PROFILE,service,instance.id)
    try:
        wait(app,lambda:not dialog.busy)
        remote.drop=True;dialog.save.click();wait(app,lambda:not dialog.busy)
        assert not dialog.save.isEnabled() and not dialog.submit.isEnabled()
        assert 'не подтверждён' in dialog.status.text() and len(remote.items)==1
        remote.drop=False
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            dialog.reload.click();wait(app,lambda:not dialog.busy)
        assert dialog.save.isEnabled() and len(remote.calls)==1
        assert dialog.workspace.item['id']==next(iter(remote.items))
    finally:dialog.dirty=False;dialog.close();dialog.deleteLater();app.processEvents()


def test_native_picker_attaches_existing_website_draft_without_creating_a_copy(tmp_path):
    from tests.test_creator_page_sync import draft
    app=QApplication.instance() or QApplication([])
    service,instance=fixture(tmp_path);remote=Remote();page=draft();remote.items[page['id']]=page
    dialog=CreatorPageDialog(remote,PROFILE,service,instance.id)
    try:
        wait(app,lambda:not dialog.busy)
        dialog.existing.setCurrentIndex(dialog.existing.findData(page['id']))
        assert dialog.attach.isEnabled()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.Yes):
            dialog.attach.click();wait(app,lambda:not dialog.busy)
        assert dialog.workspace.item['id']==page['id'] and remote.calls==[]
        assert dialog.fields['summary'].text()==page['content']['summary']
    finally:dialog.dirty=False;dialog.close();dialog.deleteLater();app.processEvents()


def test_account_change_during_save_clears_previous_account_fields(tmp_path):
    from nexus_launcher.nexus_account import SessionRejected
    from tests.test_creator_page_sync import draft
    app=QApplication.instance() or QApplication([])
    service,instance=fixture(tmp_path);remote=Remote();page=draft();remote.items[page['id']]=page
    dialog=CreatorPageDialog(remote,PROFILE,service,instance.id)
    try:
        wait(app,lambda:not dialog.busy)
        saved=dialog.workspace.attach(page['id']);dialog.complete('attach',saved,None)
        dialog.tabs.setCurrentIndex(3)
        with patch.object(remote,'creator_pages',side_effect=SessionRejected('Synthetic account switch')):
            dialog.save.click();wait(app,lambda:not dialog.busy)
        assert dialog.content is None and dialog.fields['name'].text()==''
        assert not dialog.save.isEnabled() and 'Аккаунт изменён' in dialog.status.text()
        assert page['id'] not in dialog.reference.text() and dialog.existing.count()==1
    finally:dialog.dirty=False;dialog.close();dialog.deleteLater();app.processEvents()


def test_studio_uses_account_service_from_embedded_launcher_host(tmp_path):
    from types import SimpleNamespace
    from nexus_launcher.studio_ui import StudioPage
    from nexus_launcher.creator_services import Capabilities
    app=QApplication.instance() or QApplication([])
    service,instance=fixture(tmp_path);remote=Remote()
    host=QWidget();host.services=SimpleNamespace(account_client=remote,account_profile=PROFILE)
    page=StudioPage(service.instances,host)
    try:
        page.service.capabilities=Capabilities('creator');page.refresh()
        with patch('nexus_launcher.creator_page_ui.CreatorPageDialog') as window:
            page.open_website_application()
            assert window.call_args.args[0] is remote and window.call_args.args[1] is PROFILE
            window.return_value.exec.assert_called_once()
    finally:page.close();host.close();page.deleteLater();host.deleteLater();app.processEvents()


def test_editor_tabs_keep_edits_and_primary_actions_fit_compact_windows(tmp_path):
    from PySide6.QtCore import Qt,QPoint
    from PySide6.QtTest import QTest
    app=QApplication.instance() or QApplication([])
    service,instance=fixture(tmp_path);remote=Remote()
    dialog=CreatorPageDialog(remote,PROFILE,service,instance.id)
    try:
        dialog.show();wait(app,lambda:not dialog.busy)
        dialog.fields['summary'].setText('Unsaved text must survive tab changes')
        dialog.tabs.tabBar().setFocus();QTest.keyClick(dialog.tabs.tabBar(),Qt.Key_Right)
        assert dialog.tabs.currentIndex()==1
        dialog.tabs.setCurrentIndex(3);dialog.tabs.setCurrentIndex(0)
        assert dialog.fields['summary'].text()=='Unsaved text must survive tab changes' and dialog.dirty
        for width,height in [(1160,860),(820,760),(780,680)]:
            dialog.resize(width,height);app.processEvents();QTest.qWait(80)
            # A native window manager may clamp a requested window to its work
            # area. Exact pixel sizes are deterministic only in offscreen Qt;
            # native coverage still checks the real viewport and every action.
            if app.platformName()=='offscreen':
                assert dialog.width()==width and dialog.height()==height
            assert dialog.minimumWidth()==780 and dialog.minimumHeight()==680
            assert dialog.width()>=780 and dialog.height()>=680
            assert dialog.rail_scroll.isVisible()==(dialog.width()>=1040 and dialog.height()>=780)
            for button in (dialog.save,dialog.submit):
                origin=button.mapTo(dialog,QPoint(0,0))
                assert origin.x()>=0 and origin.y()>=0
                assert origin.x()+button.width()<=dialog.width() and origin.y()+button.height()<=dialog.height()
            for index in range(dialog.tabs.count()):
                dialog.tabs.setCurrentIndex(index);app.processEvents()
                scroll=dialog.tabs.widget(index)
                assert isinstance(scroll,QScrollArea) and scroll.horizontalScrollBar().maximum()==0
    finally:dialog.dirty=False;dialog.close();dialog.deleteLater();app.processEvents()
