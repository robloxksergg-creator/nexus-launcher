from copy import deepcopy
import time
import pytest
from PySide6.QtWidgets import QDialog
from nexus_launcher.modrinth_provider import ProviderError
from nexus_launcher.mod_batch import resolve_batch
from nexus_launcher.nexus_platform.mod_install_confirmation import ModInstallConfirmation
from tests.test_next_shell import candidate  # noqa: F401


class Provider:
    def __init__(self):self.calls=[]
    def versions(self,project,*args):
        self.calls.append(project)
        return [{'id':project+'-v','project_id':project,'dependencies':([] if project=='shared' else [{'dependency_type':'required','project_id':'shared'}])}]
    def version(self,key):return {'id':key,'project_id':'shared','loaders':['fabric'],'game_versions':['1.21.1']}


def test_batch_deduplicates_shared_dependency_and_requests():
    provider=Provider()
    plan=resolve_batch(provider,['a','b'],'1.21.1','fabric')
    assert [v['project_id'] for v in plan]==['shared','a','b']
    assert provider.calls==['a','shared','b']


def test_batch_conflicting_exact_versions_rejected():
    provider=Provider()
    provider.versions=lambda project,*a:[{'id':project+'-v','project_id':project,'dependencies':[{'dependency_type':'required','project_id':'shared','version_id':'dep-'+project}]}]
    with pytest.raises(ProviderError,match='разные версии'):resolve_batch(provider,['a','b'],'1.21.1','fabric')


def test_checkboxes_only_install_on_explicit_batch_action(candidate,monkeypatch):
    app,window,_=candidate
    page=window.instances_page;catalog=page.mod_catalog
    instance=window.instance_service.create('Batch fixture','1.21.1','fabric','0.16.10')
    catalog.instance=instance
    catalog._received(catalog.generation,{'hits':[{'project_id':key,'title':key,'versions':['1.21.1'],'categories':['fabric']} for key in ('a','b','shared')]},'')
    provider=Provider();monkeypatch.setattr(page.provider,'versions',provider.versions)
    confirmations=[];transfers=[]
    def confirm(dialog):
        confirmations.append([dialog.items.item(i).text() for i in range(dialog.items.count())]);return QDialog.Accepted
    monkeypatch.setattr(ModInstallConfirmation,'exec',confirm)
    monkeypatch.setattr(page.installer,'install',lambda *a,**k:(transfers.append(deepcopy(k['resolved_versions'])) or []))
    for index in (0,1):catalog.results.itemWidget(catalog.results.item(index)).batch_check.click()
    assert not provider.calls and not transfers
    assert catalog.batch_install.text()=='Скачать выбранные · 2'
    catalog.batch_install.click()
    deadline=time.monotonic()+4
    while catalog.install_busy and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert not catalog.install_busy
    assert len(confirmations)==1 and len(transfers)==1
    assert len(transfers[0])==3
    assert sum('Выбранный мод' in s for s in confirmations[0])==2
    assert sum('Обязательная зависимость' in s for s in confirmations[0])==1


def test_batch_cancel_never_calls_installer(candidate,monkeypatch):
    app,window,_=candidate
    page=window.instances_page;catalog=page.mod_catalog
    instance=window.instance_service.create('Cancel batch','1.21.1','fabric','0.16.10');catalog.instance=instance
    monkeypatch.setattr(page.provider,'versions',Provider().versions)
    monkeypatch.setattr(ModInstallConfirmation,'exec',lambda self:QDialog.Rejected)
    calls=[];monkeypatch.setattr(page.installer,'install',lambda *a,**k:calls.append(1))
    page._catalog_install_batch(instance.id,['a','b'])
    deadline=time.monotonic()+4
    while catalog.install_busy and time.monotonic()<deadline:
        app.processEvents();time.sleep(.01)
    assert not catalog.install_busy and not calls
