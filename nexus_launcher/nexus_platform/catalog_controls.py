"""Catalogue-only painted controls and in-window popovers; no OS popup styles."""
from PySide6.QtCore import Qt, QSize, QRect, QRectF, QEvent, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QFont
from PySide6.QtWidgets import (
    QPushButton, QFrame, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QStyledItemDelegate, QStyle,
    QLayout, QWidget,
)
from shiboken6 import isValid
from .theme_tokens import TOKENS as T, TYPE, RADIUS


def tag_label(value: str) -> str:
    return {'neoforge': 'NeoForge', 'worldgen': 'World Gen'}.get(
        value, value if value[:1].isdigit() else value.replace('-', ' ').title())


def check(painter, x, y):
    path = QPainterPath()
    path.moveTo(x, y + 4)
    path.lineTo(x + 4, y + 8)
    path.lineTo(x + 11, y)
    painter.drawPath(path)


class NexusButton(QPushButton):
    def __init__(self, text='', parent=None, *, variant='secondary', chevron=False):
        super().__init__(text, parent)
        self.variant = variant
        self.chevron = chevron
        self.keyboard_focus = False
        font = QFont('Segoe UI')
        font.setPixelSize(TYPE['label'])
        self.setFont(font)
        self.setMinimumHeight(36)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 32 +
                     (22 if self.chevron or self.isCheckable() else 0), 38)

    def minimumSizeHint(self):
        return QSize(min(80, self.sizeHint().width()), 36)

    def focusInEvent(self, event):
        self.keyboard_focus = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        primary = self.variant == 'primary'
        selected = self.isChecked()
        background = T['accent'] if primary else T['wash'] if selected else T['background'] if self.variant in ('chip', 'selector') else T['surface']
        if self.underMouse() and self.isEnabled() and not primary:
            background = T['hover']
        border = T['accent'] if selected or (self.hasFocus() and self.keyboard_focus) else T['border']
        if self.variant == 'quiet' and not self.underMouse() and not self.hasFocus():
            border = background = T['surface']
        if not self.isEnabled():
            p.setOpacity(.45)
        p.setBrush(QColor(background))
        p.setPen(QPen(QColor(border), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), RADIUS['control'], RADIUS['control'])
        ink = T['background'] if primary else T['text']
        p.setPen(QColor(ink))
        left = 14 + (20 if selected and self.isCheckable() else 0)
        right = 30 if self.chevron else 14
        rect = self.rect().adjusted(left, 0, -right, 0)
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, max(0, rect.width()))
        align = Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignLeft if self.chevron else Qt.AlignmentFlag.AlignHCenter)
        p.drawText(rect, align, text)
        p.setPen(QPen(QColor(ink if primary else T['accent'] if selected else T['muted']), 1.6))
        if selected and self.isCheckable():
            check(p, 13, self.height() / 2 - 4)
        if self.chevron:
            x, y = self.width() - 20, self.height() / 2 - 2
            p.drawLine(int(x - 4), int(y), int(x), int(y + 4))
            p.drawLine(int(x), int(y + 4), int(x + 4), int(y))


class ChoiceDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = index.data(Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked.value or bool(index.data(Qt.ItemDataRole.UserRole + 1))
        current = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = QRectF(option.rect).adjusted(3, 2, -3, -2)
        painter.setBrush(QColor(T['wash'] if checked else T['hover'] if current else T['sidebar']))
        painter.setPen(QPen(QColor(T['border'] if current else T['wash'] if checked else T['sidebar']), 1))
        painter.drawRoundedRect(rect, 6, 6)
        painter.setFont(option.font)
        painter.setPen(QColor(T['text']))
        text_rect = option.rect.adjusted(34, 0, -12, 0)
        caption = option.fontMetrics.elidedText(str(index.data() or ''), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, caption)
        if checked:
            painter.setPen(QPen(QColor(T['accent']), 1.7))
            check(painter, option.rect.x() + 13, option.rect.center().y() - 4)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(180, 38)

    def editorEvent(self, event, model, option, index):
        return False  # Entire-row activation is owned below, never Qt checkbox paint/hitboxes.


class ChoiceList(QListWidget):
    activated_choice = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(ChoiceDelegate(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f'QListWidget{{background:{T["sidebar"]};border:0;outline:0;}}')
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.itemClicked.connect(lambda item: self.activated_choice.emit(item))

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.currentItem()
            if item:
                self.activated_choice.emit(item)
            event.accept()
            return
        super().keyPressEvent(event)


class ChoicePopup(QFrame):
    def __init__(self, control):
        super().__init__(control.window())
        self.control = control
        self.anchor = control
        self.setObjectName('nexusCatalogPopover')
        self.setStyleSheet(f'QFrame#nexusCatalogPopover{{background:{T["sidebar"]};border:1px solid {T["border"]};border-radius:8px;}}')
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск…')
        self.search.setAccessibleName('Поиск в списке')
        self.search.setClearButtonEnabled(True)
        root.addWidget(self.search)
        self.list = ChoiceList(self)
        root.addWidget(self.list, 1)
        footer = QHBoxLayout()
        self.clear_button = NexusButton('Очистить', variant='quiet')
        self.done_button = NexusButton('Готово', variant='quiet')
        footer.addWidget(self.clear_button)
        footer.addStretch()
        footer.addWidget(self.done_button)
        root.addLayout(footer)
        self.done_button.clicked.connect(self.close_popup)
        self.hide()

    def open_popup(self, anchor=None):
        self.anchor = anchor or self.control
        self.setParent(self.control.window())
        width = min(max(280, self.anchor.width()), self.parentWidget().width() - 32)
        height = min(330, self.parentWidget().height() - 64)
        pos = self.parentWidget().mapFromGlobal(self.anchor.mapToGlobal(self.anchor.rect().bottomLeft()))
        x = max(16, min(pos.x(), self.parentWidget().width() - width - 16))
        y = pos.y() + 6
        if y + height > self.parentWidget().height() - 16:
            y = max(40, pos.y() - self.anchor.height() - height - 6)
        self.setGeometry(x, y, width, height)
        self.show()
        self.raise_()
        self._event_targets = [self.window(), *self.window().findChildren(QWidget)]
        for target in self._event_targets:
            target.installEventFilter(self)
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)

    def close_popup(self):
        for target in getattr(self, '_event_targets', ()):
            if isValid(target):
                target.removeEventFilter(self)
        self._event_targets = []
        self.hide()
        self.anchor.setFocus(Qt.FocusReason.PopupFocusReason)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.close_popup()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            position = event.globalPosition().toPoint()
            if not self.rect().contains(self.mapFromGlobal(position)) and not self.anchor.rect().contains(self.anchor.mapFromGlobal(position)):
                self.close_popup()
        return False


class CatalogComboBox(NexusButton):
    """Small single-choice selector retaining catalogue's value/signal contract."""
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__('', parent, variant='selector', chevron=True)
        self.values = []
        self._index = -1
        self.popup = ChoicePopup(self)
        self.popup.clear_button.hide()
        self.popup.done_button.hide()
        self.popup.list.activated_choice.connect(self._choose)
        self.popup.search.textChanged.connect(self._filter)
        self.popup.search.returnPressed.connect(self._choose_visible)
        self.clicked.connect(self.showPopup)

    def addItem(self, text, value):
        self.values.append((text, value))
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, value)
        self.popup.list.addItem(item)
        if self._index < 0:
            self.setCurrentIndex(0)

    def currentData(self):
        return self.values[self._index][1] if self._index >= 0 else None

    def currentIndex(self):
        return self._index

    def findData(self, value):
        return next((i for i, (_, item) in enumerate(self.values) if item == value), -1)

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self.values):
            return
        changed = self._index != index
        self._index = index
        self.setText(self.values[index][0])
        self.setToolTip(self.values[index][0])
        for row in range(self.popup.list.count()):
            self.popup.list.item(row).setData(Qt.ItemDataRole.UserRole + 1, row == index)
        if changed:
            self.currentIndexChanged.emit(index)

    def _choose(self, item):
        self.setCurrentIndex(self.findData(item.data(Qt.ItemDataRole.UserRole)))
        self.hidePopup()

    def _choose_visible(self):
        for i in range(self.popup.list.count()):
            if not self.popup.list.item(i).isHidden():
                self._choose(self.popup.list.item(i))
                return

    def _filter(self, text):
        for i in range(self.popup.list.count()):
            item = self.popup.list.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def showPopup(self):
        if self.popup.isVisible():
            self.hidePopup()
        else:
            self.popup.search.clear()
            self.popup.open_popup()
            self.popup.list.setCurrentRow(self._index)

    def hidePopup(self):
        self.popup.close_popup()

    def view(self):
        return self.popup.list


class FlowLayout(QLayout):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(8)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._arrange(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        return QSize(max((item.minimumSize().width() for item in self.items), default=0), 38)

    def _arrange(self, rect, measure):
        x, y, row_height = rect.x(), rect.y(), 0
        for item in self.items:
            size = item.sizeHint()
            width = min(size.width(), rect.width())
            if x > rect.x() and x + width > rect.right() + 1:
                x = rect.x()
                y += row_height + self.spacing()
                row_height = 0
            if not measure:
                item.setGeometry(QRect(x, y, width, size.height()))
            x += width + self.spacing()
            row_height = max(row_height, size.height())
        return y + row_height - rect.y()

