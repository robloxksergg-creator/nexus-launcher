import json
import os
import time

from PySide6.QtCore import Qt

from nexus_launcher.nexus_platform.catalog_provider import CatalogProvider
from tests.test_next_shell import candidate  # noqa: F401


def wait_for_library(app, host):
    deadline = time.monotonic() + 10
    while not host.library_overlay.isVisible() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert host.library_overlay.isVisible(), (host.page.script_errors, host._library_geometry_pending)


def test_search_filters_preserve_game_loader_and_paging(monkeypatch):
    provider = CatalogProvider()
    observed = {}
    monkeypatch.setattr(provider, "_get", lambda path, params: observed.update(path=path, params=params) or {})
    provider.search_page("sodium", "1.21.1", "fabric", category="optimization", side="client",
                         sort="downloads", offset=20)
    facets = json.loads(observed["params"]["facets"])
    assert ["versions:1.21.1"] in facets
    assert ["categories:fabric"] in facets
    assert ["categories:optimization"] in facets
    assert any("environment:client_and_server" in group for group in facets)
    assert not any("_side:" in value for group in facets for value in group)
    assert observed["params"]["offset"] == 20
    assert observed["params"]["index"] == "downloads"


def test_catalog_timeout_and_project_profile(candidate, monkeypatch):  # noqa: F811
    app, window, _ = candidate
    catalog = window.instances_page.mod_catalog
    catalog._timeout()
    assert '12 секунд' in catalog.status.text()
    catalog._received(catalog.generation, {'hits': [{'project_id': 'abc', 'title': 'Example'}]}, '')
    catalog._project_received(catalog.detail_generation, {
        'title': 'Example', 'body': '<script>not executable</script>',
        'game_versions': ['1.21.1'], 'loaders': ['fabric'], 'license': {'name': 'MIT'},
    }, '')
    assert '1.21.1' in catalog.project_metadata.text()
    assert '<script>' not in catalog.detail.toPlainText()
    assert 'not executable' not in catalog.detail.toPlainText()
    old = catalog.detail.toPlainText()
    catalog._project_received(catalog.detail_generation - 1, {'title': 'stale'}, '')
    assert catalog.detail.toPlainText() == old


def test_real_service_workspace_embeds_without_legacy_shell(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.prototype_host import PrototypeHost
    app, window, _ = candidate
    host = PrototypeHost(window)
    host.show()
    try:
        host._command('packs')
        wait_for_library(app, host)
        assert host.surfaces.currentWidget() is host.view
        assert window.instances_page.parentWidget() is host.library_overlay
        assert host.library_overlay.x() > 0
        assert host.library_overlay.y() > 0
        assert not host.back_to_design.isVisible()
        assert not window.isVisible()
        host._return_design()
        assert host.surfaces.currentWidget() is host.view
    finally:
        host.close()


def test_embedded_library_creates_persistent_pack(candidate):  # noqa: F811
    from PySide6.QtCore import QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from nexus_launcher.instance_ui import CreateInstanceDialog
    from nexus_launcher.nexus_platform.presentation_style import stylesheet
    from nexus_launcher.nexus_platform.prototype_host import PrototypeHost

    app, window, _ = candidate
    host = PrototypeHost(window)
    host.show()
    try:
        window.config['reducedMotion'] = False
        host._command('packs')
        wait_for_library(app, host)
        page = window.instances_page
        assert host.styleSheet() == stylesheet()
        assert page.window() is host
        assert page.graphicsEffect() is None
        observed = []

        def complete_dialog():
            dialog = QApplication.activeModalWidget()
            observed.append(isinstance(dialog, CreateInstanceDialog))
            if isinstance(dialog, CreateInstanceDialog):
                dialog.name.setText('Проверка создания')
                dialog.loader.setCurrentText('Vanilla')
                dialog.accept()

        QTimer.singleShot(150, complete_dialog)
        button = next(button for button in page.library.findChildren(QPushButton)
                      if button.text() == 'Создать сборку')
        QTest.mouseClick(button, Qt.LeftButton)
        app.processEvents()
        assert observed == [True]
        instance = window.instance_service.list()[0]
        assert instance.name == 'Проверка создания'
        assert window.instance_service.load(instance.id).name == instance.name
        assert page.library_stack.currentWidget() is page.detail_surface
        assert page.pack_cards.count() == 1
        host._return_design()
        host._command('packs')
        wait_for_library(app, host)
        assert page.library_stack.currentWidget() is page.library
        assert page.pack_cards.count() == 1
        assert not page.pack_cards.item(0).isHidden()
        assert page.pack_cards.isVisible()
        assert page.graphicsEffect() is None
        original_x = host.library_overlay.x()
        host.page.runJavaScript("document.querySelector('.navigation-toggle').click()")
        deadline = time.monotonic() + 3
        while host.library_overlay.x() >= original_x and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert host.library_overlay.x() < original_x
        host.page.runJavaScript("document.querySelector('.navigation-toggle').click()")
        deadline = time.monotonic() + 3
        while host.library_overlay.x() < original_x and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert host.library_overlay.x() == original_x
        if os.environ.get('NEXUS_EMBED_CAPTURE'):
            from PySide6.QtTest import QTest
            QTest.qWait(250)
            host.grab().save(os.environ['NEXUS_EMBED_CAPTURE'])
        host.page.runJavaScript("document.querySelector('.nav [data-view=overview]').click()")
        deadline = time.monotonic() + 5
        while host._library_active and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert not host._library_active
        assert not host.library_overlay.isVisible()
        assert host.surfaces.currentWidget() is host.view
    finally:
        host.close()


def test_catalog_context_stale_error_empty_and_paging(candidate, monkeypatch):  # noqa: F811
    app, window, _ = candidate
    instance = window.instance_service.create("Каталог тест", "1.21.1", "vanilla")
    window.show_instances()
    page = window.instances_page
    page.refresh(instance.id)
    catalog = page.mod_catalog
    hits = [{"project_id": "sodium", "title": "Sodium", "downloads": 12, "description": "test"}]
    monkeypatch.setattr(catalog.provider, "search_page", lambda *a, **k: {"hits": hits, "total_hits": 42})
    page.open_mod_catalog()
    deadline = time.monotonic() + 3
    while not catalog.results.count() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert catalog.results.count() == 1
    if os.environ.get("NEXUS_CATALOG_CAPTURE"):
        window.resize(1366, 768)
        app.processEvents()
        assert window.grab().save(os.environ["NEXUS_CATALOG_CAPTURE"])
    assert "1.21.1" in catalog.destination.text()
    assert page.library_stack.currentWidget() is catalog
    assert not page.page_state.isVisible()
    assert catalog.next.isEnabled()
    catalog._received(catalog.generation, {"hits": hits * 20, "total_hits": 42}, "")
    app.processEvents()
    header_position = catalog.destination.mapTo(window, catalog.destination.rect().topLeft())
    bar = catalog.results.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(bar.maximum())
    assert catalog.destination.mapTo(window, catalog.destination.rect().topLeft()) == header_position
    for width, height in ((1280, 720), (1920, 1080)):
        window.resize(width, height)
        app.processEvents()
        assert catalog.results.viewport().height() > 250
        assert catalog.install.geometry().right() < catalog.width()
    from PySide6.QtTest import QTest
    window.raise_()
    window.activateWindow()
    catalog.sort.setFocus(Qt.TabFocusReason)
    QTest.qWait(100)
    catalog.sort.showPopup()
    app.processEvents()
    assert catalog.sort.view().isVisible()
    catalog.sort.hidePopup()
    catalog.results.setCurrentRow(0)
    assert not catalog.install.isEnabled()  # Vanilla is not a mod loader.
    token = catalog.generation
    catalog.query.setText("new query")
    catalog._received(token, {"hits": hits}, "")
    assert catalog.results.count() == 0
    catalog._received(catalog.generation, {}, "Сеть недоступна")
    assert "повторить" in catalog.status.text()
    catalog._received(catalog.generation, {"hits": [], "total_hits": 0}, "")
    assert "не найдено" in catalog.status.text()
    assert not catalog.next.isEnabled()
    page._close_catalog()
    assert page.library_stack.currentWidget() is page.detail_surface
    assert catalog.results.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_catalog_install_routes_to_selected_instance_and_busy_blocks_repeat(candidate, monkeypatch):  # noqa: F811
    app, window, _ = candidate
    instance = window.instance_service.create("Fabric", "1.21.1", "fabric", "0.19.3")
    window.show_instances()
    page = window.instances_page
    page.refresh(instance.id)
    catalog = page.mod_catalog
    monkeypatch.setattr(catalog.provider, "search_page", lambda *a, **k: {"hits": [], "total_hits": 0})
    page.open_mod_catalog()
    observed = []
    monkeypatch.setattr(page, "_resolve_install", lambda *args: observed.append(args))
    catalog._received(catalog.generation, {"hits": [{"project_id": "project", "title": "Mod"}]}, "")
    catalog.results.setCurrentRow(0)
    assert catalog.install.isEnabled()
    catalog._install_selected()
    deadline = time.monotonic() + 2
    while not observed and time.monotonic() < deadline:
        time.sleep(.01)
    catalog._install_selected()
    assert observed == [(instance.id, "project")]
    assert not catalog.install.isEnabled()
    catalog.set_install_busy(False)
    assert catalog.install.isEnabled()


def test_mod_opens_dedicated_page_and_returns_to_same_results(candidate, monkeypatch):  # noqa: F811
    from PySide6.QtTest import QTest
    app, window, _ = candidate
    instance = window.instance_service.create('Проверка каталога', '1.21.1', 'fabric')
    window.show_instances()
    page = window.instances_page
    page.refresh(instance.id)
    catalog = page.mod_catalog
    monkeypatch.setattr(catalog.provider, 'search_page', lambda *a, **k: {'hits': [], 'total_hits': 0})
    monkeypatch.setattr(catalog.provider, 'project', lambda _: {
        'title': 'Sodium', 'description': 'Оптимизация отрисовки',
        'body': '# Sodium\n\n**Быстрая отрисовка**\n\n' + '\n\n'.join(['Описание мода'] * 70),
        'game_versions': ['1.21.1'], 'loaders': ['fabric'], 'license': {'name': 'LGPL'},
    })
    monkeypatch.setattr(catalog.provider, 'versions', lambda *a: [
        {'name': 'Sodium 0.6', 'loaders': ['fabric'], 'game_versions': ['1.21.1'], 'changelog': '## Изменения\nИсправления'}])
    page.open_mod_catalog()
    QTest.qWait(100)
    catalog._received(catalog.generation, {'hits': [{'project_id': 'sodium', 'title': 'Sodium',
        'author': 'jellysquid3', 'description': 'Оптимизация отрисовки', 'downloads': 238232231}]}, '')
    row = catalog.results.item(0)
    assert catalog.results.itemWidget(row) is not None
    if os.environ.get('NEXUS_MOD_ROWS_CAPTURE'):
        window.grab().save(os.environ['NEXUS_MOD_ROWS_CAPTURE'])
    catalog._open_project(row)
    deadline = time.monotonic() + 3
    while catalog.project_title.text() != 'Sodium' and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert catalog.profile_page.isVisible()
    assert not catalog.results.isVisible()
    assert not catalog.search_header.isVisible()
    assert catalog.project_tabs.count() == 4
    assert 'Быстрая отрисовка' in catalog.detail.toPlainText()
    assert 'Sodium 0.6' in catalog.versions.toPlainText()
    assert catalog.detail.loadResource(2, None) is None
    if os.environ.get('NEXUS_MOD_PAGE_CAPTURE'):
        window.grab().save(os.environ['NEXUS_MOD_PAGE_CAPTURE'])
    catalog._close_project()
    assert catalog.results.isVisible()
    assert catalog.results.currentItem() is row
