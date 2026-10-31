"""Shared desktop chrome using the OS move/resize operations, not JS privileges."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QIcon
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from nexus_launcher.nexus_platform.theme_tokens import TOKENS
from nexus_launcher.nexus_platform.catalog_controls import NexusButton


class WindowButton(NexusButton):
    """Semantic native button with vector chrome, without platform focus glyphs."""

    def __init__(self, symbol, parent):
        super().__init__("", parent)
        self.symbol = symbol

    def mouseDoubleClickEvent(self, event):
        # A second click belongs to this control, never to title-bar drag/maximize.
        event.accept()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown():
            painter.fillRect(self.rect(), QColor(TOKENS["wash"]))
        elif self.underMouse():
            painter.fillRect(
                self.rect(),
                QColor(TOKENS["danger"] if self.symbol == "close" else TOKENS["hover"]),
            )
        if self.hasFocus() and self.keyboard_focus:
            painter.setPen(QPen(QColor(TOKENS["accent"]), 1))
            painter.drawRect(QRectF(self.rect()).adjusted(2, 2, -2, -2))
        painter.setPen(
            QPen(
                QColor(TOKENS["muted"] if not self.isEnabled() else TOKENS["text"]), 1.3
            )
        )
        cx, cy = self.width() / 2, self.height() / 2
        if self.symbol == "minimize":
            painter.drawLine(int(cx - 5), int(cy + 3), int(cx + 5), int(cy + 3))
        elif self.symbol == "close":
            painter.drawLine(int(cx - 4), int(cy - 4), int(cx + 4), int(cy + 4))
            painter.drawLine(int(cx + 4), int(cy - 4), int(cx - 4), int(cy + 4))
        elif self.symbol == "restore":
            painter.drawRect(QRectF(cx - 2, cy - 5, 8, 8))
            painter.fillRect(QRectF(cx - 5, cy - 2, 8, 8), QColor(TOKENS["sidebar"]))
            painter.drawRect(QRectF(cx - 5, cy - 2, 8, 8))
        else:
            painter.drawRect(QRectF(cx - 5, cy - 5, 10, 10))


class TitleBar(QFrame):
    def __init__(self, window, *, dialog=False):
        super().__init__(window)
        self.owner = window
        self.dialog_mode = dialog
        self.setObjectName("desktopTitleBar")
        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            #desktopTitleBar {{background:{TOKENS["sidebar"]};color:{TOKENS["text"]};}}
            QLabel {{color:{TOKENS["muted"]};font:600 11px 'Segoe UI';padding-left:12px;}}
            QPushButton {{border:0;border-radius:0;padding:0;min-width:0;min-height:0;background:transparent;color:{TOKENS["text"]};font:16px 'Segoe UI';}}
            QPushButton:hover {{background:{TOKENS["hover"]};}}
            QPushButton:focus {{border:1px solid {TOKENS["accent"]};}}
            QPushButton#windowClose:hover {{background:#a83242;}}
        """)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        from pathlib import Path
        import sys
        resources = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[2]))
        brand = QLabel(self)
        brand.setPixmap(QIcon(str(resources / 'assets' / 'nexus-mark.svg')).pixmap(30, 24))
        brand.setFixedWidth(42)
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(brand)
        label = QLabel(window.windowTitle() if dialog else "N E X U S", self)
        if dialog:
            window.windowTitleChanged.connect(label.setText)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(label)
        layout.addStretch()
        self.minimize = self._button(
            "minimize", "Свернуть NEXUS", window.showMinimized, layout
        )
        self.maximize = self._button(
            "maximize", "Развернуть", self.toggle_maximized, layout
        )
        self.close_button = self._button("close", "Закрыть NEXUS", window.close, layout)
        self.close_button.setObjectName("windowClose")
        if dialog:
            self.minimize.hide()
            self.maximize.hide()
            self.close_button.setAccessibleName("Закрыть окно")
            self.close_button.setToolTip("Закрыть окно")

    def _button(self, glyph, name, action, layout):
        button = WindowButton(glyph, self)
        button.setFixedSize(46, 36)
        button.setAccessibleName(name)
        button.setToolTip(name)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def toggle_maximized(self):
        # Let Windows/Qt own the normal geometry and the complete state transition.
        # Setting geometry during showNormal races native resize/compositor events.
        if self.owner.isMaximized() or self.owner.isFullScreen():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()
        self.sync()

    def sync(self):
        maximized = self.owner.isMaximized() or self.owner.isFullScreen()
        name = "Восстановить размер" if maximized else "Развернуть"
        self.maximize.symbol = "restore" if maximized else "maximize"
        self.maximize.setProperty("windowExpanded", maximized)
        self.maximize.update()
        self.maximize.setToolTip(name)
        self.maximize.setAccessibleName(name)
        self.setVisible(not self.owner.isFullScreen())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            if self.owner.isMaximized():
                self.toggle_maximized()
                point = event.globalPosition().toPoint()
                self.owner.move(
                    point.x() - self.owner.width() // 2, point.y() - self.height() // 2
                )
            self.owner.windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.dialog_mode:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if isinstance(self.childAt(event.position().toPoint()), WindowButton):
                event.accept()
                return
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)


class ResizeEdge(QFrame):
    def __init__(self, window, edges, cursor):
        super().__init__(window)
        self.edges = edges
        self.setCursor(cursor)
        self.setStyleSheet("background:transparent;border:0;")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window().windowHandle():
            self.window().windowHandle().startSystemResize(self.edges)
            event.accept()
        else:
            super().mousePressEvent(event)


def create_resize_edges(window):
    E, C = Qt.Edge, Qt.CursorShape
    return [
        ResizeEdge(window, edges, cursor)
        for edges, cursor in (
            (E.LeftEdge, C.SizeHorCursor),
            (E.RightEdge, C.SizeHorCursor),
            (E.TopEdge, C.SizeVerCursor),
            (E.BottomEdge, C.SizeVerCursor),
            (E.TopEdge | E.LeftEdge, C.SizeFDiagCursor),
            (E.TopEdge | E.RightEdge, C.SizeBDiagCursor),
            (E.BottomEdge | E.LeftEdge, C.SizeBDiagCursor),
            (E.BottomEdge | E.RightEdge, C.SizeFDiagCursor),
        )
    ]


def position_resize_edges(window):
    size, width, height = 6, window.size().width(), window.size().height()
    title = getattr(window, "title_bar", None)
    # Native resize hit regions must not sit above the title-bar button hit areas.
    right_start = title.height() if title else size
    top_end = (
        (title.close_button if title.dialog_mode else title.minimize).mapTo(
            window, (title.close_button if title.dialog_mode else title.minimize).rect().topLeft()
        ).x()
        if title
        else width - size
    )
    geometries = [
        (0, size, size, height - 2 * size),
        (width - size, right_start, size, max(0, height - right_start - size)),
        (size, 0, max(0, top_end - size), size),
        (size, height - size, width - 2 * size, size),
        (0, 0, size, size),
        (width - size, 0, size, size),
        (0, height - size, size, size),
        (width - size, height - size, size, size),
    ]
    for index, (edge, geometry) in enumerate(zip(window.resize_edges, geometries)):
        edge.setGeometry(*geometry)
        edge.setVisible(
            not window.isMaximized()
            and not window.isFullScreen()
            and not (title and index == 5)
        )
        edge.raise_()
