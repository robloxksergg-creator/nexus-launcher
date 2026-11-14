"""Real Qt layouts and existing handlers, using owned synthetic instances only."""
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox

from nexus_launcher.user_instances import InstanceService
from nexus_launcher.instance_ui import CreateInstanceDialog
from nexus_launcher.nexus_platform.pack_library import PackLibraryPage
from nexus_launcher.nexus_platform.native_style import install_native_style
from nexus_launcher.nexus_platform.workspace_visuals import reveal


@pytest.fixture
def workspace(tmp_path):
    app = QApplication.instance() or QApplication([])
    # Windows offscreen platform does not enumerate system fonts automatically.
    if not QFontDatabase.families():
        for name in ('segoeui.ttf', 'segoeuib.ttf', 'bahnschrift.ttf'):
            path = Path('C:/Windows/Fonts') / name
            if path.is_file():QFontDatabase.addApplicationFont(str(path))
    install_native_style(app)
    service = InstanceService(tmp_path / 'instances')
    instance = service.create('Синтетическая сборка', '1.21.1', 'vanilla')
    page = PackLibraryPage(service)
    page.setProperty('reducedMotion', True)
    page.show()
    page.refresh(instance.id)
    yield app, page, service, instance
    page.shutdown_catalog()
    page.close()
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('size', [(900, 740), (1280, 800), (1920, 1080)])
def test_bounded_layout_and_reachable_settings(workspace, size):
    app, page, _, _ = workspace
    page.resize(*size)
    page._select_tab('Настройки')
    QTest.qWait(30)
    assert page.library_stack.width() <= 1240
    assert page.detail_scroll.horizontalScrollBar().maximum() == 0
    save = next(b for b in page.findChildren(QPushButton) if b.text() == 'Сохранить параметры')
    page.detail_scroll.ensureWidgetVisible(save)
    app.processEvents()
    assert not save.visibleRegion().isEmpty()
    assert page.memory.maximumWidth() == 660


def test_save_original_handler_and_navigation(workspace, monkeypatch):
    app, page, service, instance = workspace
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: QMessageBox.Ok)
    page._select_tab('Настройки')
    page.memory.setValue(6144)
    page.jvm.setText('-Dsynthetic=true')
    save = next(b for b in page.findChildren(QPushButton) if b.text() == 'Сохранить параметры')
    save.click()
    assert service.load(instance.id).memory_mb == 6144
    assert service.load(instance.id).jvm_args == ['-Dsynthetic=true']
    page._select_tab('Обзор')
    button = next(b for b in page.findChildren(QPushButton) if b.text() == 'Управлять модами')
    button.click()
    assert page.detail.tabText(page.detail.currentIndex()) == 'Моды'
    assert page.mods_empty.isVisible()
    assert page.mods_empty.action.isEnabled()


def test_creation_fields_survive_scrolling_and_expansion(workspace):
    app, page, _, _ = workspace
    dialog = CreateInstanceDialog(page)
    from nexus_launcher.nexus_platform.dialog_presentation import polish_creation
    polish_creation(dialog)
    polish_creation(dialog)  # Idempotent when the host's event filter polishes twice.
    dialog.show()
    dialog.name.setText('Мой тестовый мир')
    dialog.minecraft.setText('1.21.1')
    advanced = next(b for b in dialog.findChildren(QPushButton) if 'Дополнительные настройки' in b.text())
    advanced.click()
    app.processEvents()
    assert dialog.memory.isVisible()
    advanced.click()
    assert dialog.values()[0] == 'Мой тестовый мир'
    assert dialog.values()[1] == '1.21.1'
    dialog.reject()


def test_reduced_motion_has_no_animation(workspace):
    _, page, _, _ = workspace
    reveal(page)
    assert getattr(page, '_workspace_reveal', None) is None
