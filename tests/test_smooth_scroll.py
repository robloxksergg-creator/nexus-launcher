import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint, QPointF, Qt, QAbstractAnimation
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from nexus_launcher.nexus_platform.smooth_scroll import SmoothScroll


def test_wheel_animates_and_accumulates_without_jumping():
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.services = SimpleNamespace(config={})
    controller = SmoothScroll(owner)
    area = QScrollArea(owner)
    area.resize(200, 150)
    content = QWidget()
    content.setMinimumSize(100, 2000)
    area.setWidget(content)
    owner.resize(200, 150)
    owner.show()
    app.processEvents()

    def wheel(delta=-120, pixel=None):
        event = QWheelEvent(QPointF(10, 10), QPointF(10, 10), pixel or QPoint(), QPoint(0, delta),
                            Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        QApplication.sendEvent(area.viewport(), event)

    try:
        wheel()
        assert area.verticalScrollBar().value() == 0
        # Drive Qt's clock deterministically. Its global animation driver can
        # suspend after prior WebEngine windows close in a full offscreen suite.
        # Verify interpolation and accumulation rather than wall-clock timing.
        animation = controller.animations[id(area.verticalScrollBar())][0]
        assert animation.state() == QAbstractAnimation.Running
        animation.setCurrentTime(60)
        assert 0 < area.verticalScrollBar().value() < 100
        before = area.verticalScrollBar().value()
        changes = []
        area.verticalScrollBar().valueChanged.connect(changes.append)
        wheel()
        animation = controller.animations[id(area.verticalScrollBar())][0]
        assert area.verticalScrollBar().value() == before
        animation.setCurrentTime(180)
        assert changes == sorted(changes)
        assert area.verticalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
        assert area.verticalScrollBar().value() == 200
        assert controller.animations
        wheel()
        animation = controller.animations[id(area.verticalScrollBar())][0]
        animation.setCurrentTime(60)
        before = area.verticalScrollBar().value()
        changes.clear()
        wheel(120)
        animation = controller.animations[id(area.verticalScrollBar())][0]
        assert area.verticalScrollBar().value() == before
        animation.setCurrentTime(90)
        animation.setCurrentTime(180)
        assert changes == sorted(changes, reverse=True)
        assert area.verticalScrollBar().value() == before - 100
        wheel()
        animation = controller.animations[id(area.verticalScrollBar())][0]
        wheel(pixel=QPoint(0, -5))
        assert animation.state() != QAbstractAnimation.Running
        owner._web_reduced_motion = True
        wheel()
        assert all(animation.state() != QAbstractAnimation.Running for animation, _ in controller.animations.values())
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()


def test_paint_timer_and_layout_skip_widget_ancestry():
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.services = SimpleNamespace(config={})
    controller = SmoothScroll(owner)
    class PaintTarget:
        def parentWidget(self):
            raise AssertionError('Paint path must not walk widget ancestry')
    from PySide6.QtCore import QEvent
    for kind in (QEvent.Paint, QEvent.Timer, QEvent.LayoutRequest, QEvent.UpdateRequest):
        assert controller.eventFilter(PaintTarget(), QEvent(kind)) is False
    owner.deleteLater()
    app.processEvents()
