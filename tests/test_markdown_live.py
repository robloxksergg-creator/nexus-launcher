"""Explicit live Windows content QA. Never part of deterministic acceptance."""
import json
import os
import time
from pathlib import Path
import pytest
from PySide6.QtGui import QImage, QPixmap, QTextCursor
from PySide6.QtTest import QTest
from nexus_launcher.nexus_platform.catalog_provider import CatalogProvider
from nexus_launcher.nexus_platform.mod_media import CACHE, decode_image
from tests.test_next_shell import candidate  # noqa: F401

@pytest.mark.skipif(os.environ.get('NEXUS_LIVE_MARKDOWN') != '1', reason='Explicit real API/CDN visual QA only')
def test_actual_four_project_content(candidate):  # noqa: F811
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    from tests.test_design_host import wait, js
    app, services, _ = candidate
    instance = services.instance_service.create('Content QA', '1.21.1', 'fabric')
    host = DesignHost(services)
    services.hide()
    host.resize(1366, 900)
    host.show()
    output = Path('D:/nexus2/markdown-audit/screens')
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
        for slug in ('3dskinlayers', 'jei', 'antique-atlas-4', 'cobblemon-pokedex-network'):
            catalog._close_project()
            payload = provider.project(slug)
            catalog.project_hit = {'project_id': payload['id'], 'title': payload['title']}
            catalog.profile_icon.clear()
            for widget in (catalog.results, catalog.catalog_state, catalog.search_header, catalog.previous, catalog.next, catalog.install):
                widget.hide()
            catalog.profile_page.show()
            catalog._project_received(catalog.detail_generation, payload, '')
            catalog.project_tabs.setCurrentIndex(0)
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline:
                app.processEvents()
                if (catalog.profile_icon.pixmap() and all(label.pixmap() and not label.pixmap().isNull() for label in catalog.gallery_labels)
                        and 'Загрузка изображения…' not in catalog.detail.toPlainText()):
                    break
                time.sleep(.02)
            body = catalog.detail
            assert catalog.profile_icon.pixmap(), slug
            expected = QPixmap.fromImage(decode_image(CACHE.get(payload['icon_url']), width=88, dimension=2048))
            assert catalog.profile_icon.pixmap().toImage().convertToFormat(QImage.Format.Format_RGBA8888) == expected.toImage().convertToFormat(QImage.Format.Format_RGBA8888), slug
            assert catalog.gallery_labels and all(label.pixmap() and not label.pixmap().isNull() for label in catalog.gallery_labels), slug
            assert 'Загрузка изображения…' not in body.toPlainText(), slug
            if slug == '3dskinlayers':
                assert 'cdn.modrinth.com' not in payload['body']
                assert not body.images  # External authored images must remain blocked.
                for label, domain in [('Discord', 'discord.gg'), ('GitHub', 'github.com'), ('Modrinth', 'modrinth.com'), ('CurseForge', 'www.curseforge.com')]:
                    cursor = body.document().find(label)
                    assert not cursor.isNull() and cursor.charFormat().isAnchor(), label
                    assert domain in cursor.charFormat().anchorHref(), label
                body.verticalScrollBar().setValue(0)
            else:
                assert body.images, slug
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
            QTest.qWait(150)
            assert host.grab().save(str(output / f'{slug}-overview.png'))
            assert body.horizontalScrollBar().maximum() == 0, (slug, body.viewport().width(), body.document().textWidth(), body.document().idealWidth())
            if slug == '3dskinlayers':
                cursor = body.document().find('Discord')
                cursor.clearSelection()
                body.setTextCursor(cursor)
                body.ensureCursorVisible()
                QTest.qWait(150)
                assert host.grab().save(str(output / '3dskinlayers-links.png'))
            catalog.project_tabs.setCurrentIndex(2)
            QTest.qWait(150)
            assert catalog.gallery.horizontalScrollBar().maximum() == 0
            assert host.grab().save(str(output / f'{slug}-gallery.png'))
            results.append({'project': slug, 'icon': True, 'body_images': len(body.images), 'gallery_images': len(catalog.gallery_labels), 'body_external_only': slug == '3dskinlayers', 'fallbacks': body.toPlainText().count('Изображение недоступно.'), 'links': [label for label in ('Discord', 'GitHub', 'Modrinth', 'CurseForge') if body.document().find(label).charFormat().isAnchor()]})
            host.resize(1000, 720)
            catalog.project_tabs.setCurrentIndex(0)
            QTest.qWait(150)
            assert body.horizontalScrollBar().maximum() == 0, slug
            host.resize(1366, 900)
            QTest.qWait(150)
        catalog._close_project()
        catalog._received(catalog.generation, provider.search_page('JEI', '1.21.1', 'fabric'), '')
        wait(app, lambda: catalog.results.count() > 0 and not catalog.results.item(0).icon().isNull())
        QTest.qWait(150)
        assert host.grab().save(str(output / 'search-icons.png'))
        (output.parent / 'live-results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    finally:
        host.close()
