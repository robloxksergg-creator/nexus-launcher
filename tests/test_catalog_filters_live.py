"""Opt-in real Modrinth and Windows UI acceptance in isolated QA storage."""
import json
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from tests.test_next_shell import candidate  # noqa: F401


def wait(app, condition, timeout=20):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition()


@pytest.mark.skipif(os.environ.get('NEXUS_LIVE_FILTERS') != '1', reason='opt-in API/Windows screenshots')
def test_real_filter_dialog_responsive_and_install_route(candidate, monkeypatch):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    from nexus_launcher.modrinth_provider import ModInstaller
    import certifi
    # This isolated Python runtime lacks a CDN issuer in its default CA store.
    # Use verified Mozilla roots for this test only; never disable TLS verification
    # or change the protected provider/secure_http implementation.
    monkeypatch.setenv('SSL_CERT_FILE', certifi.where())
    app, services, _root = candidate
    out = Path('D:/nexus2/filter-audit-v25')
    out.mkdir(exist_ok=True)
    instance = services.instance_service.create('Фильтры QA', '1.21.1', 'fabric', '0.19.3')
    host = DesignHost(services)
    host.show()
    host.raise_()
    host.activateWindow()
    catalog = services.instances_page.mod_catalog
    try:
        host._action('open-build', instance.id)
        services.instances_page.open_mod_catalog()
        wait(app, lambda: catalog.results.count() > 0 and host.library_overlay.isVisible())
        catalog._open_filters()
        wait(app, lambda: bool(catalog._tags))
        panel = catalog.filter_panel
        assert panel.categories.list.count() == len(catalog._tags['categories'])
        panel.categories.search.setText('optimization')
        for index in range(panel.categories.list.count()):
            item = panel.categories.list.item(index)
            if item.data(Qt.UserRole) == 'optimization':
                item.setCheckState(Qt.Checked)
        # A real tag-backed environment control is present, even when the
        # selected Sodium example itself supports a different environment.
        assert panel.environment.findData('client_and_server') >= 0
        layouts = []
        for width, height in ((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)):
            host.resize(width, height)
            app.processEvents()
            QTest.qWait(120)
            panel.grab().save(str(out / f'filters-{width}x{height}.png'))
            host.grab().save(str(out / f'integrated-{width}x{height}.png'))
            assert panel.width() < host.width()
            assert panel.height() < host.height()
            assert panel.card.geometry().right() < catalog.width()
            for selector in (panel.versions, panel.loaders):
                assert selector.width() >= 180
                selector.showPopup()
                app.processEvents()
                assert selector.popup.parentWidget() is host
                assert host.rect().contains(selector.popup.geometry())
                selector.popup.grab().save(str(out / f'{selector.title}-{width}.png'))
                selector.popup.close_popup()
            layouts.append({'size': [width, height], 'card': [panel.card.width(), panel.card.height()]})
        panel.extra_button.setChecked(True)
        app.processEvents()
        panel.grab().save(str(out / 'extra-filters.png'))
        panel.categories.showPopup(anchor=panel.more_categories)
        app.processEvents()
        panel.categories.popup.grab().save(str(out / 'all-categories.png'))
        panel.categories.popup.close_popup()
        panel.accept()
        catalog.sort.showPopup()
        app.processEvents()
        catalog.sort.popup.grab().save(str(out / 'sorting.png'))
        catalog.sort.hidePopup()
        catalog.query.setText('sodium')
        catalog.search()
        wait(app, lambda: catalog.results.count() > 0)
        assert catalog.filter_state.categories == ('optimization',)
        assert all('optimization' in catalog.results.item(i).data(Qt.UserRole + 1)['categories']
                   for i in range(catalog.results.count()))
        for width, height in ((1280, 720), (1366, 768), (1920, 1080), (2560, 1440)):
            host.resize(width, height)
            app.processEvents()
            QTest.qWait(150)
            host.grab().save(str(out / f'results-{width}x{height}.png'))
            assert catalog.results.viewport().height() > 220
            assert catalog.install.geometry().right() < catalog.width()
            assert catalog.width() <= host.width()
        # Before image uses the backed-up pre-change widget over real API data.
        namespace = {'__name__': 'nexus_launcher.nexus_platform.catalog_before', '__package__': 'nexus_launcher.nexus_platform'}
        old_source = Path('D:/nexus2/backups/source-before-filters-v24/nexus_platform/mod_catalog.py')
        exec(compile(old_source.read_text(encoding='utf-8'), str(old_source), 'exec'), namespace)
        before = namespace['ModCatalog']()
        try:
            before.instance = instance
            before.destination.setText(catalog.destination.text())
            before.resize(1366, 768)
            before.show()
            before._received(before.generation, catalog.provider.search_page('', '1.21.1', 'fabric'), '')
            QTest.qWait(300)
            before.grab().save(str(out / 'before-filters.png'))
        finally:
            before.shutdown()
            before.close()
        # Real Install signal is routed to the unchanged verified installer,
        # confined to candidate's temporary instance, without launching Minecraft.
        catalog.results.setCurrentRow(0)
        item = catalog.results.currentItem()
        project = item.data(Qt.UserRole)
        assert catalog.install.isEnabled()
        installs = []
        catalog.install_requested.disconnect()
        def install(instance_id, project_id):
            installs.extend(ModInstaller(services.instance_service).install(instance_id, project_id))
        catalog.install_requested.connect(install)
        catalog._install_selected()
        assert installs
        root = services.instance_service.path_for(instance.id)
        assert all((root / 'mods' / mod.filename).is_file() for mod in installs)
        (out / 'live-ui-results.json').write_text(json.dumps({
            'layouts': layouts, 'state': repr(catalog.filter_state), 'resultCount': catalog.total,
            'installedProject': project, 'installedFiles': [mod.filename for mod in installs],
            'instanceRoot': str(root), 'scriptErrors': host.page.script_errors,
        }, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        host.close()
