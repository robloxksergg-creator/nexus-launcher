import io
import time
import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage
from nexus_launcher.nexus_platform import mod_media as media
from tests.test_next_shell import candidate  # noqa: F401

URL = 'https://cdn.modrinth.com/data/test/icon.png'

def png(width=20, height=20):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(0xff3377aa)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    assert image.save(buffer, 'PNG')
    return bytes(buffer.data().data())

class Reply(io.BytesIO):
    def __init__(self, data, length=None):
        super().__init__(data)
        self.headers = {'Content-Length': str(length if length is not None else len(data))}
        self.reads = 0
    def read(self, size=-1):
        self.reads += 1
        return super().read(size)

@pytest.fixture
def transport(monkeypatch):
    replies = []
    monkeypatch.setattr(media, 'CACHE', media.MediaCache())
    def open_mock(request):
        reply = Reply(png())
        replies.append(reply)
        return reply
    monkeypatch.setattr(media, 'open_media', open_mock)
    return replies

@pytest.mark.parametrize('url', ['http://cdn.modrinth.com/a.png', 'https://evil.test/a.png', 'file:///a.png', 'data:image/png,a', 'javascript:alert(1)', 'https://user@cdn.modrinth.com/a', 'https://cdn.modrinth.com:444/a'])
def test_invalid_origins_never_download(transport, url):
    assert media.fetch_media(url) == b''
    assert not transport

def test_valid_images_shared_cache_and_cancellation(transport):
    assert media.fetch_media(URL) == png()
    assert media.fetch_media(URL) == png()
    assert len(transport) == 1
    assert media.fetch_media(URL, lambda: True) == b''

@pytest.mark.parametrize('data', [b'<svg></svg>', b'corrupt', b'\x89PNG\r\n\x1a\n', b'a' * (media.MAX_BYTES + 1)], ids=['svg', 'corrupt', 'truncated', 'oversize'])
def test_invalid_bytes_not_cached(monkeypatch, transport, data):
    monkeypatch.setattr(media, 'open_media', lambda request: Reply(data))
    assert media.fetch_media(URL) == b''
    assert media.CACHE.get(URL) is None

def test_dimensions_and_content_length(monkeypatch, transport):
    reply = Reply(png(), media.MAX_BYTES + 1)
    monkeypatch.setattr(media, 'open_media', lambda request: reply)
    assert media.fetch_media(URL) == b''
    assert reply.reads == 0
    assert media.decode_image(png(4097, 1)).isNull()

def test_failure_does_not_poison_cache(monkeypatch, transport):
    monkeypatch.setattr(media, 'open_media', lambda request: Reply(b'corrupt'))
    assert not media.fetch_media(URL)
    monkeypatch.setattr(media, 'open_media', lambda request: Reply(png()))
    assert media.fetch_media(URL)

def test_cache_bounds_ttl_keys():
    data = png()
    cache = media.MediaCache(budget=len(data) * 2, capacity=2, ttl=.01)
    for index in range(3):
        cache.put(URL + str(index), data)
    assert len(cache.entries) == 2
    assert cache.bytes <= cache.budget
    assert cache.get(URL + '0') is None
    cache.put('https://evil.test/a', data)
    cache.put(URL, b'corrupt')
    assert cache.get(URL) is None
    time.sleep(.02)
    assert cache.get(URL + '1') is None

def test_body_multiple_images_loading_success_failure_and_stale(candidate, monkeypatch):  # noqa: F811
    from nexus_launcher.nexus_platform.project_content import ProjectBody
    from PySide6.QtCore import QUrl
    body = ProjectBody()
    body.resize(1000, 600)
    body.show()
    candidate[0].processEvents()
    class Future:
        def cancel(self):
            pass
    monkeypatch.setattr(body._pool, 'submit', lambda *args: Future())
    second = URL + '?second'
    body.setMarkdown(f'![one]({URL})\n\n![two]({second})')
    assert body.toPlainText().count('Загрузка изображения…') == 2
    body._media_received(body.generation - 1, URL, png())
    assert not body.images
    body._media_received(body.generation, URL, png(900, 450))
    assert body.loadResource(2, QUrl(URL)) is not None
    assert body.toPlainText().count('Загрузка изображения…') == 1
    body._media_received(body.generation, second, b'corrupt')
    assert 'Загрузка изображения…' not in body.toPlainText()
    assert 'Изображение недоступно.' in body.toPlainText()
    assert body.loadResource(2, QUrl('file:///secret')) is None
    body.resize(500, 400)
    candidate[0].processEvents()
    assert body.horizontalScrollBar().maximum() == 0
    body.close()

def test_verified_tls_and_redirect_policy(monkeypatch):
    import ssl
    import urllib.request
    observed = []
    reply = Reply(png())
    reply.geturl = lambda: 'https://evil.test/icon.png'
    class Opener:
        def open(self, request, timeout):
            assert timeout == 5
            return reply
    def build(*handlers):
        observed.extend(handlers)
        return Opener()
    monkeypatch.setattr(urllib.request, 'build_opener', build)
    with pytest.raises(ValueError):
        media.open_media(urllib.request.Request(URL))
    assert reply.closed
    context = observed[1]._context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    with pytest.raises(ValueError):
        observed[0].validate('http://cdn.modrinth.com/image.png')

def test_missing_icon_has_placeholder(candidate):  # noqa: F811
    _, window, _ = candidate
    catalog = window.instances_page.mod_catalog
    catalog._received(catalog.generation, {'hits': [{'project_id': 'missing', 'title': 'Missing'}]}, '')
    item = catalog.results.item(0)
    widget = catalog.results.itemWidget(item)
    assert widget is not None
    from PySide6.QtWidgets import QLabel
    icons = [label.pixmap() for label in widget.findChildren(QLabel) if label.pixmap()]
    assert icons and not icons[0].isNull()

def test_search_and_detail_icons_gallery_stale_empty(candidate, monkeypatch):  # noqa: F811
    app, window, _ = candidate
    from nexus_launcher.nexus_platform import mod_catalog
    monkeypatch.setattr(mod_catalog, 'fetch_media', lambda *args, **kwargs: png())
    catalog = window.instances_page.mod_catalog
    catalog._received(catalog.generation, {'hits': [{'project_id': 'test', 'title': 'Test', 'icon_url': URL}]}, '')
    catalog._project_received(catalog.detail_generation, {'title': 'Test', 'icon_url': URL, 'body': '', 'gallery': [{'url': URL, 'title': 'Second', 'ordering': 2}, {'url': URL, 'title': 'Featured', 'featured': True}]}, '')
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        app.processEvents()
        if catalog.gallery_labels[0].pixmap() and not catalog.results.item(0).icon().isNull():
            break
        time.sleep(.01)
    assert not catalog.results.item(0).icon().isNull()
    assert catalog.results.iconSize().width() == 0
    assert catalog.profile_icon.pixmap() and not catalog.profile_icon.pixmap().isNull()
    assert len(catalog.gallery_labels) == 2
    assert catalog.gallery_labels[0].accessibleName() == 'Featured'
    before = catalog.profile_icon.pixmap().cacheKey()
    catalog._profile_icon_received(catalog.detail_generation - 1, png(40, 40))
    assert catalog.profile_icon.pixmap().cacheKey() == before
    catalog._project_received(catalog.detail_generation, {'title': 'Empty', 'body': '', 'gallery': []}, '')
    assert catalog.gallery_labels == []
