"""Render the project vector mark into native application icon formats."""
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QByteArray, QRectF
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def build(root):
    assets = Path(root) / 'assets'
    renderer = QSvgRenderer(QByteArray((assets / 'nexus-mark.svg').read_bytes()))
    if not renderer.isValid():
        raise ValueError('Invalid NEXUS brand vector')
    image = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter, QRectF(40, 192, 944, 640))
    painter.end()
    if not image.save(str(assets / 'icon.png')):
        raise OSError('Could not save brand PNG')
    with Image.open(assets / 'icon.png') as source:
        source.save(assets / 'icon.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
        source.save(assets / 'control-panel.png')
        source.save(assets / 'control-panel.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
        source.save(assets / 'icon.icns', sizes=[(n, n) for n in (16, 32, 64, 128, 256, 512, 1024)])


if __name__ == '__main__':
    build(Path(__file__).resolve().parents[1])
