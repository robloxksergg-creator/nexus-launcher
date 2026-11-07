"""Offscreen Qt acceptance, synthetic project and client; no network or game process."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
from PySide6.QtWidgets import QApplication,QPushButton
from PySide6.QtCore import QDateTime
from nexus_launcher.creator_services import Capabilities
from nexus_launcher.creator_catalogue_ui import CreatorCatalogueDialog
from nexus_launcher.studio_ui import StudioPage
from nexus_launcher.user_instances import InstanceService


def wait(app,predicate):
    end=time.monotonic()+5
    while time.monotonic()<end:
        app.processEvents()
        if predicate():return
        time.sleep(.01)
    raise AssertionError('Qt result deadline')


def test_real_studio_plan_controls_save_reload_and_clear_inactive_dates(tmp_path):
    app=QApplication.instance() or QApplication([])
    instances=InstanceService(tmp_path)
    instance=instances.create('Synthetic release','1.21.1','vanilla')
    page=StudioPage(instances)
    try:
        page.service.capabilities=Capabilities('creator')
        page.refresh()
        page.release_access.setCurrentIndex(page.release_access.findData('PRIVATE'))
        enabled,date=page.release_dates['websiteAt']
        enabled.setChecked(True)
        date.setDateTime(QDateTime.currentDateTime().addDays(10))
        page.release_destination.setCurrentIndex(page.release_destination.findData('launcher'))
        assert not enabled.isChecked() and not enabled.isEnabled()
        launch_enabled,launch_date=page.release_dates['launcherAt']
        launch_enabled.setChecked(True)
        launch_date.setDateTime(QDateTime.currentDateTime().addDays(35))
        assert page.save()
        saved=page.service.load(instance.id)['releasePlan']
        assert saved['access']=='PRIVATE' and saved['websiteAt'] is None
        assert saved['launcherAt'].endswith(':00.000Z')
        page._select(0)
        assert page._release_plan()==saved
    finally:page.close();page.deleteLater();app.processEvents()


def test_real_catalogue_only_allows_reviewed_website_action_and_handles_failure():
    app=QApplication.instance() or QApplication([])
    class Client:
        fail=False
        def creator_catalogue(self,after=None):
            if self.fail:raise RuntimeError('synthetic secret must not reach UI')
            return {'next':None,'items':[dict(name='Synthetic community',summary='Test only',genre='RPG',version='1.21.1',loader='fabric',access='PRIVATE',website='/servers/community-test')]}
    client=Client();dialog=CreatorCatalogueDialog(client)
    try:
        wait(app,lambda:dialog.refresh.isEnabled())
        buttons=dialog.findChildren(QPushButton)
        download=next(b for b in buttons if b.text().startswith('Скачивание:'))
        assert not download.isEnabled()
        assert any(b.text()=='Открыть страницу на сайте' for b in buttons)
        client.fail=True;dialog.load()
        wait(app,lambda:dialog.refresh.isEnabled())
        assert 'недоступен' in dialog.status.text() and 'secret' not in dialog.status.text()
        assert dialog.rows.count()==0
    finally:dialog.close();dialog.deleteLater();app.processEvents()
