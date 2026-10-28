"""Security and usability checks for presentation adapters, using real Qt widgets."""
import os
from pathlib import Path

import pytest
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QTimer, QUrl
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMenu, QPushButton, QScrollArea

from tests.test_next_shell import candidate  # noqa: F401
from nexus_launcher.nexus_platform.project_content import ProjectBody, safe_link, safe_image


@pytest.mark.parametrize('url', ['file:///C:/secret.png', 'javascript:alert(1)', 'data:text/html,test',
                                 'http://cdn.modrinth.com/a.png', 'https://user@cdn.modrinth.com/a.png',
                                 'https://cdn.modrinth.com:444/a.png', 'https://cdn.modrinth.com.evil/a.png'])
def test_untrusted_image_urls_are_rejected(url):
    assert not safe_image(url)


def test_rich_content_is_readable_and_inert(candidate, monkeypatch):  # noqa: F811
    app, _, _ = candidate
    body = ProjectBody()
    submitted = []
    class Future:
        def cancel(self):
            pass
    monkeypatch.setattr(body._pool, 'submit', lambda *args: submitted.append(args) or Future())
    body.resize(700, 500)
    body.show()
    body.setMarkdown('''<center><h1>Название мода</h1></center>
<p>Описание <strong>важного</strong> и <em>полезного</em>.</p>
<ul><li>Первый</li><li>Второй</li></ul><hr>
<img src="file:///C:/secret.png" onerror="bad()">
<img src="https://cdn.modrinth.com/example.png" alt="Скриншот">
<script>secret-script</script><iframe>secret-frame</iframe>
<a href="javascript:alert(1)">Плохая ссылка</a>
[Хорошая ссылка](https://modrinth.com/mod/example)
## Изменения
**Исправлено** отображение.
''')
    app.processEvents()
    text = body.toPlainText()
    assert all(word in text for word in ['Название мода', 'важного', 'полезного', 'Первый', 'Второй', 'Изменения', 'Исправлено'])
    assert all(word not in text for word in ['<h1>', '<img', '<center>', '**', 'secret-script', 'secret-frame', 'onerror'])
    assert 'Изображение недоступно.' in text
    assert len(submitted) == 1
    assert submitted[0][-1] == 'https://cdn.modrinth.com/example.png'
    assert body.loadResource(2, QUrl('file:///C:/secret.png')) is None
    document = body.document()
    bold = document.find('важного')
    assert bold.charFormat().fontWeight() >= 600
    italic = document.find('полезного')
    assert italic.charFormat().fontItalic()
    link = document.find('Плохая ссылка')
    assert not link.charFormat().isAnchor()
    assert safe_link(document.find('Хорошая ссылка').charFormat().anchorHref())
    token = body.generation
    body._media_received(token - 1, submitted[0][-1], b'invalid')
    assert body.toPlainText() == text
    body._media_received(token, submitted[0][-1], b'invalid')
    assert body.toPlainText().count('Изображение недоступно.') == 2
    body.setMarkdown('```html\n<h1>Пример кода</h1>\n```')
    assert '<h1>Пример кода</h1>' in body.toPlainText()
    body.close()


def test_safe_image_decode_and_late_generation(candidate, monkeypatch):  # noqa: F811
    _, _, _ = candidate
    body = ProjectBody()
    class Future:
        def cancel(self):
            pass
    monkeypatch.setattr(body._pool, 'submit', lambda *args: Future())
    body.setMarkdown('![image](https://cdn.modrinth.com/example.png)')
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image = QImage(800, 400, QImage.Format_RGB32)
    image.fill(0xff445566)
    assert image.save(buffer, 'PNG')
    body._media_received(body.generation, 'https://cdn.modrinth.com/example.png', bytes(data))
    assert body.images['https://cdn.modrinth.com/example.png'].width() <= 760
    body.setPlainText('Другой проект')
    body._media_received(body.generation - 1, 'https://cdn.modrinth.com/example.png', bytes(data))
    assert not body.images and body.toPlainText() == 'Другой проект'


def test_creation_adapter_preserves_fields_and_bounds(candidate):  # noqa: F811
    from nexus_launcher.instance_ui import CreateInstanceDialog
    from nexus_launcher.nexus_platform.dialog_presentation import polish_creation
    app, services, _ = candidate
    dialog = CreateInstanceDialog(services.instances_page)
    defaults = dialog.values()
    memory = dialog.memory.value()
    polish_creation(dialog)
    dialog.show()
    app.processEvents()
    assert dialog.values() == defaults and dialog.memory.value() == memory
    assert dialog.findChild(QPushButton, 'primaryAction').text() == 'Создать сборку'
    toggle = dialog.findChild(QPushButton, 'advancedToggle')
    toggle.setChecked(True)
    app.processEvents()
    assert dialog.height() <= dialog.screen().availableGeometry().height() - 80
    scroll = dialog.findChild(QScrollArea, 'creationScroll')
    assert scroll.verticalScrollBar().maximum() > 0
    for field in (dialog.name, dialog.minecraft, dialog.loader, dialog.template, dialog.loader_version,
                  dialog.install_path, dialog.icon_path, dialog.java, dialog.memory, dialog.jvm,
                  dialog.resolution_width, dialog.resolution_height, dialog.banner):
        assert not field.isHidden()
        assert dialog.isAncestorOf(field)
    captures = os.environ.get('NEXUS_UI2_CAPTURE_DIR')
    if captures:
        dialog.grab().save(str(Path(captures) / 'create-dialog-expanded.png'))
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        app.processEvents()
        dialog.grab().save(str(Path(captures) / 'create-dialog-advanced-bottom.png'))
    dialog.name.setText('Новая история')
    dialog.jvm.setText('-XX:+UseG1GC')
    instance = services.instance_service.create(*dialog.values()[:3])
    dialog.apply_options(instance)
    assert instance.jvm_args == ['-XX:+UseG1GC'] and instance.memory_mb == memory
    assert dialog.values()[0] == 'Новая история'
    dialog.reject()


def test_menu_adapter_keeps_all_original_actions(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.dialog_presentation import polish_menu
    app, services, _ = candidate
    page = services.instances_page
    instance = services.instance_service.create('Контекстное меню', '1.21.1', 'fabric')
    page.refresh(instance.id)
    captured = []
    def inspect():
        menu = next(child for child in page.findChildren(QMenu) if child.isVisible())
        original = [(action.text(), action) for action in menu.actions() if not action.isSeparator()]
        polish_menu(menu)
        assert len(original) == 10
        assert [(action.text(), action) for action in menu.actions() if not action.isSeparator()] == original
        captures = os.environ.get('NEXUS_UI2_CAPTURE_DIR')
        if captures:
            menu.grab().save(str(Path(captures) / 'build-context-menu.png'))
        captured.extend(original)
        menu.close()
    QTimer.singleShot(50, inspect)
    page._open_context_menu()
    app.processEvents()
    assert len(captured) == 10


def test_native_workspaces_at_all_review_sizes(candidate, monkeypatch):  # noqa: F811
    from PySide6.QtTest import QTest
    from tests.test_design_host import js, wait
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    app, services, _ = candidate
    instance = services.instance_service.create('История — длинное название сборки для проверки', '1.21.1', 'neoforge')
    root = services.instance_service.path_for(instance.id)
    (root / 'saves' / 'Проверочный мир').mkdir(parents=True)
    monkeypatch.setattr(services.instances_page.mod_catalog.provider, 'search_page', lambda *args, **kwargs: {'hits': [], 'total_hits': 0})
    host = DesignHost(services)
    host.show()
    services.hide()
    captures = os.environ.get('NEXUS_UI2_CAPTURE_DIR')
    try:
        wait(app, lambda: bool(js(app, host.page, '!!window.NexusUI')))
        for width, height in ((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)):
            host.resize(width, height)
            host._action('open-build', instance.id)
            wait(app, lambda: host.library_overlay.isVisible())
            page = services.instances_page
            for tab in range(page.detail.count()):
                page.detail.setCurrentIndex(tab)
                QTest.qWait(80)
                page.detail_scroll.verticalScrollBar().setValue(0)
                assert page.detail.widget(tab).width() <= host.width()
                assert page.detail.tabBar().height() < 80
                assert page.detail.tabBar().isVisible()
                for button in page.detail.widget(tab).findChildren(QPushButton):
                    if button.isVisible():
                        assert button.height() >= 36
                        assert button.parentWidget().rect().contains(button.geometry()), button.text()
                if captures:
                    host.grab().save(str(Path(captures) / f'build-tab-{tab}-{width}.png'))
                    if page.detail_scroll.verticalScrollBar().maximum():
                        page.detail_scroll.verticalScrollBar().setValue(page.detail_scroll.verticalScrollBar().maximum())
                        QTest.qWait(30)
                        host.grab().save(str(Path(captures) / f'build-tab-{tab}-{width}-bottom.png'))
                    if tab == page.detail.count() - 1 and width == 1366:
                        for subtab in range(page.advanced_tabs.count()):
                            page.advanced_tabs.setCurrentIndex(subtab)
                            QTest.qWait(80)
                            host.grab().save(str(Path(captures) / f'files-subtab-{subtab}.png'))
            page.show_library()
            QTest.qWait(80)
            card = page.pack_cards.itemWidget(page.pack_cards.item(0))
            assert card.worlds == 1
            assert card.open.geometry().right() < card.play.geometry().left()
            if captures:
                host.grab().save(str(Path(captures) / f'builds-{width}.png'))
    finally:
        host.close()
