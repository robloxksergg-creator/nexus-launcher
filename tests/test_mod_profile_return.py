from PySide6.QtTest import QTest
from tests.test_next_shell import candidate  # noqa: F401
from tests.test_design_host import wait


def test_installed_profile_returns_to_build_not_synthetic_catalog(candidate,monkeypatch):
    app,window,_=candidate
    page=window.instances_page;catalog=page.mod_catalog
    instance=window.instance_service.create('Return fixture','1.21.1','fabric','0.16.10')
    page.refresh(instance.id);window._navigate('library','');page.detail.setCurrentIndex(1)
    monkeypatch.setattr(catalog.provider,'project',lambda key:{'id':key,'title':'Test mod','body':'Description'})
    monkeypatch.setattr(catalog.provider,'versions',lambda *a:[])
    count=catalog.results.count()
    page._open_installed_mod(instance.id,'mod','Test mod')
    assert catalog.return_results.text()=='← Назад к модам сборки'
    assert catalog.results.count()==count
    catalog.install_requested.disconnect(page._catalog_install)
    requested=[];catalog.install_requested.connect(lambda instance_id,project_id:requested.append(project_id))
    catalog.profile_install.click()
    assert requested==['mod']
    catalog.return_results.click();app.processEvents()
    assert page.library_stack.currentWidget() is page.detail_surface
    assert page.detail.currentIndex()==1
    assert catalog.results.count()==count
    # Searching for new mods still works after returning from the installed one.
    hit={'project_id':'another','title':'Another mod','versions':['1.21.1'],'categories':['fabric']}
    monkeypatch.setattr(catalog.provider,'search_page',lambda *a,**k:{'hits':[hit]})
    page.find_mods_action.click()
    wait(app,lambda:catalog.results.count()==1)
    row=catalog.results.item(0)
    catalog._open_project(row)
    assert catalog.return_results.text()=='← Назад к результатам'
    catalog.return_results.click();app.processEvents()
    assert page.library_stack.currentWidget() is catalog
    assert catalog.results.currentItem() is row
    assert not catalog.profile_page.isVisible()


def test_find_actions_in_filter_header_and_build_search(candidate):
    app,window,_=candidate
    page=window.instances_page
    instance=window.instance_service.create('Find fixture','1.21.1','fabric','0.16.10')
    page.refresh(instance.id);window._navigate('library','');page.detail.setCurrentIndex(1)
    app.processEvents()
    assert page.find_mods_action.text()=='Найти моды'
    assert page.find_mods_action.parentWidget() is page.installed_filter.parentWidget()
    assert abs(page.find_mods_action.geometry().center().y()-page.installed_filter.geometry().center().y())<10
    page.find_build_action.click();app.processEvents()
    assert page.library_stack.currentWidget() is page.library
    assert page.pack_search.hasFocus()
