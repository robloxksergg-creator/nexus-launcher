"""Shared bounded CDN media, using the existing HTTPS origin/redirect policy."""
from collections import OrderedDict
import ssl
from threading import Lock
import time
import urllib.request

import certifi
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QLabel, QSizePolicy
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtCore import QRectF
from nexus_launcher.secure_http import origin, OriginRedirects

MAX_BYTES = 4 * 1024 * 1024
MAX_DIMENSION = 4096
FORMATS = {b'png', b'jpeg', b'jpg', b'webp', b'gif'}


def safe_image(url):
    try:
        return (isinstance(url, str) and not any(ord(c) < 32 for c in url)
                and origin(url) == ('https', 'cdn.modrinth.com', 443))
    except (ValueError, TypeError):
        return False


def decode_image(data, width=1000, dimension=MAX_DIMENSION):
    if not data or len(data) > MAX_BYTES:
        return QImage()
    buffer = QBuffer()
    buffer.setData(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    if bytes(reader.format().data()).lower() not in FORMATS:
        return QImage()
    size = reader.size()
    if not size.isValid() or max(size.width(), size.height()) > dimension:
        return QImage()
    reader.setScaledSize(size.scaled(min(width, size.width()), 1000, Qt.AspectRatioMode.KeepAspectRatio))
    return reader.read()


class MediaCache:
    def __init__(self, budget=16 * 1024 * 1024, capacity=64, ttl=300):
        self.budget, self.capacity, self.ttl = budget, capacity, ttl
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = Lock()

    def get(self, url):
        if not safe_image(url):
            return None
        with self.lock:
            entry = self.entries.pop(url, None)
            if not entry:
                return None
            when, data = entry
            if time.monotonic() - when >= self.ttl:
                self.bytes -= len(data)
                return None
            self.entries[url] = entry
            return data

    def put(self, url, data):
        # Only the downloader inserts successfully decoded, policy-checked data.
        if not safe_image(url) or not data or len(data) > min(MAX_BYTES, self.budget) or decode_image(data).isNull():
            return
        with self.lock:
            previous = self.entries.pop(url, None)
            if previous:
                self.bytes -= len(previous[1])
            while self.entries and (len(self.entries) >= self.capacity or self.bytes + len(data) > self.budget):
                _, old = self.entries.popitem(last=False)
                self.bytes -= len(old[1])
            self.entries[url] = (time.monotonic(), data)
            self.bytes += len(data)


def open_media(request):
    # Windows' installed CA roots can lag the CDN's chain. Add the maintained
    # Mozilla CA bundle ONLY to this verified CDN transport; never disable TLS
    # checks or change global/provider/updater SSL settings.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    policy = OriginRedirects({('https', 'cdn.modrinth.com', 443)})
    policy.validate(request.full_url)
    reply = urllib.request.build_opener(policy, urllib.request.HTTPSHandler(context=context)).open(request, timeout=5)
    try:
        policy.validate(reply.geturl())
    except Exception:
        reply.close()
        raise
    return reply


CACHE = MediaCache()


def fetch_media(url, cancelled=lambda: False, max_bytes=MAX_BYTES):
    max_bytes = min(MAX_BYTES, max_bytes)
    if not safe_image(url) or cancelled():
        return b''
    cached = CACHE.get(url)
    if cached is not None:
        return cached if len(cached) <= max_bytes and not cancelled() else b''
    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'NexusLauncher/2.0 (Modrinth media)'})
        with open_media(request) as reply:
            length = reply.headers.get('Content-Length')
            if length and int(length) > max_bytes:
                return b''
            chunks, count = [], 0
            while not cancelled():
                chunk = reply.read(min(64 * 1024, max_bytes - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    return b''
                chunks.append(chunk)
            data = b''.join(chunks)
        if cancelled() or decode_image(data).isNull():
            return b''
        CACHE.put(url, data)
        return data
    except Exception:
        return b''


class GalleryImage(QLabel):
    """Responsive rounded media, with a compact loading/failure state."""
    def __init__(self):
        super().__init__('Загрузка изображения…')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        self.setMaximumWidth(1000)
        self.setFixedHeight(40)

    def set_image(self, image):
        from PySide6.QtGui import QPixmap
        if image.isNull():
            self.setText('Изображение недоступно.')
            self.setFixedHeight(40)
        else:
            self.setPixmap(QPixmap.fromImage(image))
            self._fit()

    def _fit(self):
        pixmap = self.pixmap()
        if pixmap and not pixmap.isNull():
            self.setFixedHeight(max(1, round(min(self.width(), pixmap.width()) * pixmap.height() / pixmap.width())))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def paintEvent(self, event):
        pixmap = self.pixmap()
        if not pixmap or pixmap.isNull():
            return super().paintEvent(event)
        scaled = pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        rect = QRectF((self.width() - scaled.width()) / 2, 0, scaled.width(), scaled.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(rect, 16, 16)
        painter.setClipPath(path)
        painter.drawPixmap(round(rect.x()), 0, scaled)
