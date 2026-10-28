"""Opt-in real API/CDN visual evidence; excluded from deterministic acceptance."""
import json
import os
import time
from pathlib import Path
import pytest
from PySide6.QtGui import QTextCursor, QImage, QPixmap
from PySide6.QtTest import QTest
from nexus_launcher.nexus_platform.catalog_provider import CatalogProvider
from tests.test_next_shell import candidate  # noqa: F401

@pytest.mark.skipif(os.environ.get('NEXUS_LIVE_MEDIA') != '1', reason='Explicit real-network visual QA only')
def test_actual_modrinth_media(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    from tests.test_design_host import wait, js
    from nexus_launcher.nexus_platform.mod_media import CACHE, decode_image
    app, services, _ = candidate
    instance = services.instance_service.create('Media QA', '1.21.1', 'fabric')
    host = DesignHost(services)
    services.hide()
    host.resize(1366, 900)
    host.show()
    output = Path('D:/nexus2/media-audit/screens')
    output.mkdir(parents=True, exist_ok=True)
    results = []
    try:
        wait(app, lambda: js(app, host.page, "typeof window.NexusUI !== 'undefined'"))
        wait(app, lambda: bool(host._builds))
        js(app, host.page, "window.NexusUI.navigate('library','nexus_launcher.main')")
        wait(app, lambda: host.library_overlay.isVisible())
        library = services.instances_page
        catalog = library.mod_catalog
        catalog.instance = instance
        library.library_stack.setCurrentWidget(catalog)
        provider = CatalogProvider()
        for slug in ('sodium', 'antique-atlas-4', 'cobblemon-pokedex-network'):
            catalog._close_project()
            payload = provider.project(slug)
            catalog.project_hit = {'project_id': payload['id'], 'title': payload['title']}
            catalog.profile_icon.clear()
            catalog.results.hide()
            catalog.catalog_state.hide()
            for widget in (catalog.search_header, catalog.previous, catalog.next, catalog.install):
                widget.hide()
            catalog.profile_page.show()
            catalog._project_received(catalog.detail_generation, payload, '')
            catalog.project_tabs.setCurrentIndex(0)
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                app.processEvents()
                if (catalog.detail.images and catalog.profile_icon.pixmap()
                        and all(label.pixmap() and not label.pixmap().isNull() for label in catalog.gallery_labels)
                        and 'Загрузка изображения…' not in catalog.detail.toPlainText()):
                    break
                time.sleep(.02)
            assert catalog.detail.images, slug
            assert catalog.profile_icon.pixmap(), slug
            expected = decode_image(CACHE.get(payload['icon_url']), width=88, dimension=2048)
            assert catalog.profile_icon.pixmap().toImage().convertToFormat(QImage.Format.Format_RGBA8888) == QPixmap.fromImage(expected).toImage().convertToFormat(QImage.Format.Format_RGBA8888), slug
            assert catalog.gallery_labels and all(label.pixmap() and not label.pixmap().isNull() for label in catalog.gallery_labels), slug
            body = catalog.detail
            block = body.document().begin()
            first = None
            while block.isValid() and first is None:
                iterator = block.begin()
                while not iterator.atEnd():
                    fragment = iterator.fragment()
                    if fragment.charFormat().isImageFormat():
                        first = fragment.position()
                        break
                    iterator += 1
                block = block.next()
            assert first is not None
            cursor = QTextCursor(body.document())
            cursor.setPosition(first)
            body.setTextCursor(cursor)
            body.ensureCursorVisible()
            app.processEvents()
            QTest.qWait(150)
            assert host.grab().save(str(output / f'{slug}-body.png'))
            catalog.project_tabs.setCurrentIndex(2)
            app.processEvents()
            QTest.qWait(150)
            assert catalog.gallery.horizontalScrollBar().maximum() == 0
            assert host.grab().save(str(output / f'{slug}-gallery.png'))
            results.append({'project': slug, 'body_images': len(body.images), 'gallery_images': sum(bool(label.pixmap() and not label.pixmap().isNull()) for label in catalog.gallery_labels), 'gallery_total': len(catalog.gallery_labels), 'gallery_fallbacks': [label.text() for label in catalog.gallery_labels if not label.pixmap() or label.pixmap().isNull()], 'icon_verified': True})
        catalog._close_project()
        payload = provider.search_page('Sodium', '1.21.1', 'fabric')
        catalog._received(catalog.generation, payload, '')
        wait(app, lambda: catalog.results.count() > 0 and not catalog.results.item(0).icon().isNull())
        app.processEvents()
        QTest.qWait(150)
        assert host.grab().save(str(output / 'search-real-icons.png'))
        (output.parent / 'live-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    finally:
        host.close()
