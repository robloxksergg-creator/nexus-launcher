from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox
from PySide6.QtTest import QTest
from nexus_launcher.user_instances import InstalledMod
from nexus_launcher.nexus_platform.mod_install_confirmation import ModInstallConfirmation
from tests.test_next_shell import candidate  # noqa: F401


def test_catalog_installed_state_is_per_instance(candidate,monkeypatch):
    app,window,_=candidate
    catalog=window.instances_page.mod_catalog
    instance=window.instance_service.create('TLS fixture','1.21.1','fabric','0.16.10')
    catalog.instance=instance
    catalog._received(catalog.generation,{'hits':[{'project_id':'sodium','title':'Sodium','versions':['1.21.1'],'categories':['fabric']}]},'')
    item=catalog.results.item(0);catalog.results.setCurrentRow(0);catalog.project_hit=catalog.results.item(0).data(Qt.UserRole+1)
    button=catalog.results.itemWidget(item).install
    assert button.isEnabled()
    instance.installed_mods=[InstalledMod('sodium','v1','Sodium','sodium.jar','a'*128)]
    catalog.refresh_installed(instance)
    assert button.text()=='Установлен' and not button.isEnabled()
    assert catalog.profile_install.text()=='Установлен'
    other=window.instance_service.create('Other','1.21.1','fabric','0.16.10')
    catalog.refresh_installed(other)
    assert catalog.instance.id==instance.id
    instance.installed_mods=[]
    catalog.refresh_installed(instance)
    assert button.isEnabled() and button.text()=='Установить'
    page=window.instances_page
    monkeypatch.setattr(QMessageBox,'information',lambda *a:(_ for _ in ()).throw(AssertionError('success popup')))
    monkeypatch.setattr(QMessageBox,'warning',lambda *a:(_ for _ in ()).throw(AssertionError('error popup')))
    page._task_done('Установлено модов: 1')
    assert catalog.status.text()=='Установлено модов: 1'
    page._task_failed('Connection failed')
    assert 'Connection failed' in catalog.status.text()


def test_confirmation_explicit_labels_and_cancel(candidate):
    app,window,_=candidate
    dialog=ModInstallConfirmation('Test pack','iris',[{'project_id':'sodium','name':'Sodium 0.8'},{'project_id':'iris','name':'Iris 1.8'}],window)
    dialog.show();app.processEvents()
    assert dialog.items.count()==2
    assert 'Обязательная зависимость' in dialog.items.item(0).text()
    assert 'Выбранный мод' in dialog.items.item(1).text()
    assert dialog.cancel.isDefault()
    QTest.mouseClick(dialog.cancel,Qt.LeftButton)
    assert dialog.result()==QDialog.Rejected
    dialog.show();QTest.mouseClick(dialog.confirm,Qt.LeftButton)
    assert dialog.result()==QDialog.Accepted
    dialog.close()


def test_pending_and_downloading_never_mark_entire_catalog_installed(candidate):
    app,window,_=candidate
    catalog=window.instances_page.mod_catalog
    instance=window.instance_service.create('Status fixture','1.21.1','fabric','0.16.10')
    catalog.instance=instance
    catalog._received(catalog.generation,{'hits':[{'project_id':key,'title':key,'versions':['1.21.1'],'categories':['fabric']} for key in ('iris','sodium','other')]},'')
    catalog.results.setCurrentRow(0);catalog.project_hit=catalog.results.item(0).data(Qt.UserRole+1)
    def labels():return [catalog.results.itemWidget(catalog.results.item(i)).install.text() for i in range(3)]
    catalog.set_install_busy(True,instance_id=instance.id,project_id='iris')
    assert labels()==['Проверяем…','Установить','Установить']
    catalog.set_install_busy(True,phase='confirm')
    assert labels()==['Ждёт подтверждения','Установить','Установить']
    assert catalog.profile_install.text()=='Ждёт подтверждения'
    catalog.install_queue=[(instance.id,'sodium')]
    catalog._selection_changed(0)
    assert labels()==['Ждёт подтверждения','В очереди · 1','Установить']
    catalog.install_queue.clear()
    catalog.set_install_busy(False)
    assert labels()==['Установить']*3
    assert instance.installed_mods==[]
    catalog.set_install_busy(True,instance_id=instance.id,project_id='iris',phase='download',projects=['iris','sodium'])
    assert labels()==['Скачивается…','Скачивается…','Установить']
    instance.installed_mods=[InstalledMod(key,'v1',key,key+'.jar','a'*128) for key in ('iris','sodium')]
    catalog.refresh_installed(instance)
    # Completion is not displayed while a transfer is still pending.
    assert labels()==['Скачивается…','Скачивается…','Установить']
    catalog.set_install_busy(False)
    assert labels()==['Установлен','Установлен','Установить']
    assert catalog.results.itemWidget(catalog.results.item(2)).install.isEnabled()


def test_bounded_queue_removes_duplicates_and_starts_next_after_cancel(candidate,monkeypatch):
    app,window,_=candidate
    page=window.instances_page;catalog=page.mod_catalog
    instance=window.instance_service.create('Queue fixture','1.21.1','fabric','0.16.10')
    catalog.instance=instance
    launched=[]
    class Worker:
        def __init__(self,**kwargs):self.args=kwargs['args']
        def start(self):launched.append(self.args)
    monkeypatch.setattr('nexus_launcher.nexus_platform.pack_library.threading.Thread',Worker)
    page._catalog_install(instance.id,'iris')
    page._catalog_install(instance.id,'sodium')
    page._catalog_install(instance.id,'iris')
    assert len(launched)==1 and catalog.install_queue==[(instance.id,'sodium')]
    page._catalog_install(instance.id,'sodium')
    assert not catalog.install_queue
    for i in range(15):page._catalog_install(instance.id,'queued'+str(i))
    assert len(catalog.install_queue)==12 and len(launched)==1
    monkeypatch.setattr(ModInstallConfirmation,'exec',lambda self:QDialog.Rejected)
    page._confirm_install(instance.id,'iris',[{'project_id':'iris','name':'Iris'}])
    app.processEvents()
    assert len(launched)==2 and launched[-1]==(instance.id,'queued0')
    assert catalog.install_target==instance.id and catalog.install_projects=={'queued0'}
    assert len(catalog.install_queue)==11


def test_real_resolver_thread_delivers_confirmation_and_cancel_clears_busy(candidate,monkeypatch):
    import time
    app,window,_=candidate
    page=window.instances_page;catalog=page.mod_catalog
    instance=window.instance_service.create('Worker fixture','1.21.1','fabric','0.16.10')
    catalog.instance=instance
    prompts=[]
    monkeypatch.setattr(page.provider,'resolve',lambda *a:[{'project_id':'root','name':'Root'}])
    monkeypatch.setattr(ModInstallConfirmation,'exec',lambda self:(prompts.append(self.items.count()) or QDialog.Rejected))
    page._catalog_install(instance.id,'root')
    until=time.monotonic()+3
    while catalog.install_busy and time.monotonic()<until:
        app.processEvents();time.sleep(.01)
    assert prompts==[1] and not catalog.install_busy
    assert page.service.load(instance.id).installed_mods==[]
