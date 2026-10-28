"""Bounded artwork decoding and deterministic landscape fallback; no file mutation."""
import hashlib
import math

from PySide6.QtCore import QFileInfo, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImageReader, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from .theme_tokens import RADIUS, TOKENS


def landscape(seed, width=800, height=400):
    digest = hashlib.sha256(str(seed).encode()).digest()
    pixmap = QPixmap(width, height)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, width, height)
    hue = 195 + digest[0] % 35
    gradient.setColorAt(0, QColor.fromHsl(hue, 72, 53))
    gradient.setColorAt(1, QColor(TOKENS["background"]))
    painter.fillRect(pixmap.rect(), gradient)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(195, 218, 237, 110))
    painter.drawEllipse(QPointF(width * .73, height * .25), height * .09, height * .09)
    for layer in range(4):
        path = QPainterPath(QPointF(0, height))
        step = width / 20
        for index in range(21):
            level = .46 + layer * .10 + math.sin(index * .55 + digest[layer] / 20) * .09
            x, y = index * step, height * level
            path.lineTo(x, y)
            path.lineTo(x + step, y)
        path.lineTo(width, height)
        path.closeSubpath()
        painter.setBrush(QColor.fromHsl(hue + layer * 3, 45, 36 - layer * 6))
        painter.drawPath(path)
    painter.end()
    return pixmap


def load_artwork(path, seed, size=QSize(1200, 600)):
    if path and QFileInfo(str(path)).size() <= 20 * 1024 * 1024:
        reader = QImageReader(str(path))
        dimensions = reader.size()
        if 0 < dimensions.width() <= 8192 and 0 < dimensions.height() <= 8192:
            reader.setScaledSize(dimensions.scaled(size, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if not image.isNull():
                return QPixmap.fromImage(image)
    return landscape(seed, size.width(), size.height())


class ArtworkSurface(QWidget):
    """Shared crop-to-fill hero/card with a bottom readability overlay."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._art = landscape("nexus")
        self.setMinimumHeight(180)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def set_artwork(self, path, seed):
        self._art = load_artwork(path, seed)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), RADIUS["hero"], RADIUS["hero"])
        painter.setClipPath(clip)
        scaled = self._art.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        shade = QLinearGradient(0, 0, 0, self.height())
        shade.setColorAt(0, QColor(10, 14, 20, 0))
        shade.setColorAt(.4, QColor(10, 14, 20, 25))
        shade.setColorAt(1, QColor(10, 14, 20, 245))
        painter.fillRect(self.rect(), shade)
