"""Shared wheel animation for native launcher scroll surfaces."""
from PySide6.QtCore import QObject, QEvent, QPropertyAnimation, QEasingCurve, Qt
from PySide6.QtWidgets import QWidget, QAbstractScrollArea, QAbstractItemView, QComboBox
from shiboken6 import isValid
import weakref


class SmoothScroll(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.animations = {}
        self._tracked = weakref.WeakSet()
        self.track_tree(owner)
        self.track_tree(getattr(owner, 'services', None))

    def track_tree(self, root):
        if not isinstance(root, QWidget) or not isValid(root):
            return
        for widget in (root, *root.findChildren(QWidget)):
            if isValid(widget) and widget not in self._tracked:
                self._tracked.add(widget)
                widget.installEventFilter(self)

    def stop(self):
        for animation, _ in self.animations.values():
            if isValid(animation):
                animation.stop()
        for widget in tuple(self._tracked):
            if isValid(widget):
                widget.removeEventFilter(self)
        self._tracked.clear()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.ChildPolished:
            self.track_tree(event.child())
            return False
        # Paint, timer and layout events must never traverse widget ancestry.
        if event.type() not in (QEvent.Wheel, QEvent.KeyPress, QEvent.Show, QEvent.Polish):
            return False
        if event.type() in (QEvent.Show, QEvent.Polish) and not isinstance(watched, QAbstractScrollArea):
            return False
        # A global QApplication filter must only handle its owner's workspaces
        # and dialogs. Closed/other launcher windows must not consume this wheel.
        if not isValid(watched) or watched not in self._tracked:
            return False
        if isinstance(watched, QAbstractScrollArea) and event.type() in (QEvent.Show, QEvent.Polish):
            watched.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            watched.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if event.type() == QEvent.KeyPress:
            for animation, _ in self.animations.values():
                animation.stop()
            return False
        if event.type() != QEvent.Wheel or event.modifiers() & Qt.ControlModifier:
            return False
        if (getattr(self.owner.services, 'config', {}).get('reducedMotion', False)
                or getattr(self.owner, '_web_reduced_motion', False)):
            for animation, _ in self.animations.values():
                animation.stop()
            return False
        if not event.pixelDelta().isNull():
            for animation, _ in self.animations.values():
                animation.stop()
            return False  # Precision touchpads already provide continuous deltas.
        widget = watched
        while widget is not None:
            if isinstance(widget, QComboBox):
                return False
            if isinstance(widget, QAbstractScrollArea):
                if isinstance(widget, QAbstractItemView):
                    widget.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
                    widget.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
                horizontal = bool(event.modifiers() & Qt.ShiftModifier) or event.angleDelta().x() != 0
                bar = widget.horizontalScrollBar() if horizontal else widget.verticalScrollBar()
                delta = event.angleDelta().x() or event.angleDelta().y()
                key = id(bar)
                old = self.animations.get(key)
                current = bar.value()
                # Accumulate only in the same direction; reversing starts here.
                running = old and old[0].state() == QPropertyAnimation.Running
                start = old[1] if running and (old[1] - current) * delta < 0 else current
                target = max(bar.minimum(), min(bar.maximum(), start - round(delta / 120 * 100)))
                if target != bar.value():
                    if old:
                        old[0].stop()
                        old[0].deleteLater()
                    else:
                        bar.destroyed.connect(lambda _=None, k=key: self.animations.pop(k, None))
                    # A fresh timeline cannot apply an old frame while retargeting.
                    animation = QPropertyAnimation(bar, b'value', self)
                    animation.setDuration(180)
                    animation.setEasingCurve(QEasingCurve.OutCubic)
                    animation.setStartValue(bar.value())
                    animation.setEndValue(target)
                    self.animations[key] = (animation, target)
                    animation.start()
                    event.accept()
                    return True
            widget = widget.parentWidget() if hasattr(widget, 'parentWidget') else None
        return False
