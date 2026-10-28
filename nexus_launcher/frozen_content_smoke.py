"""Opt-in packaged presentation QA. No remote requests or instance writes."""
from types import SimpleNamespace
from unittest.mock import patch
from io import BytesIO

from PIL import Image
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from nexus_launcher.nexus_platform.project_content import ProjectBody


def check_content(window):
    body = ProjectBody(window)
    body.resize(700, 400)
    body.move(280, 180)
    url = 'https://cdn.modrinth.com/data/offline-content-smoke.png'
    with patch.object(body._pool, 'submit', return_value=SimpleNamespace(cancel=lambda: True)):
        body.setMarkdown(f'## Проверка содержимого\n\n[Discord](https://discord.gg/test)\n\n![]({url})\n\n<script>forbidden</script>')
    buffer = BytesIO()
    Image.new('RGB', (320, 160), (32, 51, 75)).save(buffer, format='PNG')
    body._media_received(body.generation, url, buffer.getvalue())
    body.show()
    body.raise_()
    QApplication.processEvents()
    link = body.document().find('Discord')
    result = {'markdown_link': link.charFormat().anchorHref() == 'https://discord.gg/test',
              'empty_alt_image': url in body.images,
              'active_html_removed': 'forbidden' not in body.toPlainText(),
              'local_resource_denied': body.loadResource(2, QUrl('file:///private')) is None,
              'pending_finished': 'Загрузка изображения…' not in body.toPlainText(),
              'network_calls': 0}
    assert all(value for key, value in result.items() if key != 'network_calls'), result
    return result
