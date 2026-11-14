import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QPushButton, QMessageBox
from PySide6.QtTest import QTest
from nexus_launcher.user_instances import InstalledMod
from tests.test_next_shell import candidate  # noqa: F401


def test_row_actions_filters_and_compact_diagnostics(candidate,monkeypatch):
    app,window,_=candidate
    service=window.instance_service
    instance=service.create('Мастерская модов','1.21.1','fabric','0.16.10')
    root=service.path_for(instance.id)
    instance.installed_mods=[InstalledMod('sodium','v1','Sodium','sodium.jar','a'*128),InstalledMod('local:example','v2','Локальный мод','local.jar','b'*128)]
    for name in ('sodium.jar','local.jar'):(root/'mods'/name).write_bytes(b'synthetic fixture, never executed')
    service.save(instance)
    page=window.instances_page
    page.refresh(instance.id);window._navigate('library','');page.library_stack.setCurrentWidget(page.detail_surface);page.detail.setCurrentIndex(1)
    window.resize(1200,800);window.show();app.processEvents()
    assert page.mods.count()==2
    row=page.mods.itemWidget(page.mods.item(0));toggle=row.findChild(QCheckBox)
    assert toggle and toggle.isChecked()
    toggle_left = toggle.geometry().left()
    assert toggle.width()==88
    assert toggle.geometry().left()>row.width()/2
    toggle.click();app.processEvents()
    assert page.mods.itemWidget(page.mods.item(0)).findChild(QCheckBox).geometry().left()==toggle_left
    assert not service.load(instance.id).installed_mods[0].enabled
    assert (root/'disabled_mods'/'sodium.jar').is_file()
    page.installed_filter.setCurrentIndex(1)
    assert page.mods.item(0).isHidden() and not page.mods.item(1).isHidden()
    page.installed_filter.setCurrentIndex(4)
    page.mods_search.setText('missing')
    assert all(page.mods.item(i).isHidden() for i in range(2))
    page.mods_search.clear();page.installed_filter.setCurrentIndex(0)
    assert page.diagnostics_card.isHidden()
    assert any(action.text()=='Что мешает запуску?' for action in page._build_context_menu().actions())
    assert page.launch_button.height()==page.context_button.height()==42
    captures=os.environ.get('NEXUS_MOD_ROWS_CAPTURE')
    if captures:
        Path(captures).mkdir(parents=True,exist_ok=True)
        QTest.qWait(500);page.grab().save(str(Path(captures)/'installed-mods.png'))
        menu=page._build_context_menu();menu.popup(page.context_button.mapToGlobal(page.context_button.rect().bottomLeft()))
        QTest.qWait(100);menu.grab().save(str(Path(captures)/'build-menu.png'));menu.close()
    # Row delete targets exactly that row even if another item was selected.
    page.mods.item(1).setSelected(True)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    page._mod_row_action(instance.id,'sodium.jar','delete')
    assert [m.filename for m in service.load(instance.id).installed_mods]==['local.jar']
