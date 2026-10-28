"""Inline native password visibility control; never reads or stores field text."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLineEdit, QToolButton


class PasswordVisibilityButton(QToolButton):
    def __init__(self, field: QLineEdit):
        super().__init__(field)
        self.field = field
        self.setObjectName("passwordReveal")
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(32, 32)
        field.setMinimumHeight(max(44, field.minimumHeight()))
        margins = field.textMargins()
        field.setTextMargins(margins.left(), margins.top(), margins.right() + 38, margins.bottom())
        self.setStyleSheet("""
            QToolButton#passwordReveal { padding:0; min-height:0; border:1px solid transparent;
                border-radius:6px; background:transparent; }
            QToolButton#passwordReveal:hover:enabled { background:palette(alternate-base); }
            QToolButton#passwordReveal:pressed:enabled { background:palette(midlight); }
            QToolButton#passwordReveal:focus { border:2px solid palette(highlight); }
            QToolButton#passwordReveal:disabled { color:palette(disabled, text); }
        """)
        self.toggled.connect(self._toggle)
        field.installEventFilter(self)
        self._toggle(False)
        self._position()

    def _position(self):
        self.move(max(0, self.field.width() - self.width() - 6),
                  max(0, (self.field.height() - self.height()) // 2))

    def eventFilter(self, watched, event):
        if watched is self.field and event.type() == QEvent.Type.Resize:
            self._position()
        elif watched is self.field and event.type() == QEvent.Type.Hide:
            self.setChecked(False)
        return super().eventFilter(watched, event)

    def _toggle(self, visible):
        self.field.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        label = "Скрыть пароль" if visible else "Показать пароль"
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.update()

    def keyPressEvent(self, event):
        # QToolButton otherwise lets Enter activate the dialog's default submit.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not event.isAutoRepeat():
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate((self.width() - 20) / 2, (self.height() - 20) / 2)
        painter.scale(20 / 24, 20 / 24)
        color = self.field.palette().text().color()
        if not self.isEnabled():
            color = QColor(color)
            color.setAlpha(100)
        painter.setPen(QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        path = QPainterPath(QPointF(2, 12))
        path.cubicTo(8, 2.7, 16, 2.7, 22, 12)
        path.cubicTo(16, 21.3, 8, 21.3, 2, 12)
        painter.drawPath(path)
        painter.drawEllipse(QPointF(12, 12), 3, 3)
        if not self.isChecked():
            painter.drawLine(QPointF(3, 3), QPointF(21, 21))
        painter.end()
