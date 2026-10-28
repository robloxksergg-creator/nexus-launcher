"""Reusable visual library primitives; operations remain in InstancePage."""
from PySide6.QtCore import QDateTime, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QListWidget, QPushButton, QStyledItemDelegate
from nexus_launcher.user_instances import UserInstance

from .artwork import load_artwork
from .theme_tokens import RADIUS, TOKENS, TYPE


class InstalledModDelegate(QStyledItemDelegate):
    """Paint retained native list items; selection and filenames stay authoritative."""
    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole + 2)
        if not data:
            return super().paint(painter, option, index)
        from PySide6.QtWidgets import QStyle
        painter.save()
        rect = option.rect.adjusted(0, 4, -4, -4)
        painter.setClipRect(rect)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.setPen(QPen(QColor(TOKENS['accent'] if selected else TOKENS['border']), 1))
        painter.setBrush(QColor(TOKENS['wash'] if selected else TOKENS['surface']))
        painter.drawRoundedRect(rect, 12, 12)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon:
            icon.paint(painter, QRect(rect.left() + 14, rect.top() + 14, 48, 48))
        x = rect.left() + 80
        width = max(0, rect.width() - 96)
        font = QFont('Segoe UI')
        for y, text, size, weight, color in (
            (25, data['name'], 17, QFont.Weight.DemiBold, TOKENS['text']),
            (46, data['metadata'], 12, QFont.Weight.Normal, TOKENS['muted']),
            (64, data['filename'], 12, QFont.Weight.Normal, TOKENS['muted']),
        ):
            font.setPixelSize(size)
            font.setWeight(weight)
            painter.setFont(font)
            painter.setPen(QColor(color))
            painter.drawText(x, rect.top() + y, painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideRight, width))
        if option.state & QStyle.StateFlag.State_HasFocus:
            painter.setPen(QPen(QColor(TOKENS['accent']), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 10, 10)
        painter.restore()


class ArtworkCard(QPushButton):
    play_requested = Signal()

    def __init__(self, instance: UserInstance, parent=None, worlds=None):
        super().__init__(parent)
        self.instance = instance
        self.worlds = worlds
        self.art = load_artwork(instance.banner or instance.icon, instance.id, QSize(600, 300))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Открыть {instance.name}, Minecraft {instance.minecraft_version}, {instance.loader}, {len(instance.installed_mods)} модов")
        self.setToolTip(f'{instance.name}\nMinecraft {instance.minecraft_version} · {instance.loader.title()}\nПамять: {instance.memory_mb / 1024:g} ГБ')
        self.open = QPushButton('Открыть', self)
        self.open.setAccessibleName('Открыть сборку: ' + instance.name)
        self.open.clicked.connect(self.click)
        self.play = QPushButton("▶ Играть", self)
        self.play.setObjectName("primaryAction")
        self.play.setAccessibleName("Играть: " + instance.name)
        self.play.clicked.connect(self.play_requested)
        self.setMinimumHeight(316)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.play.setGeometry(self.width() - 128, self.height() - 52, 112, 36)
        self.open.setGeometry(16, self.height() - 52, 104, 36)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        path.addRoundedRect(QRectF(bounds), RADIUS["surface"], RADIUS["surface"])
        painter.setClipPath(path)
        painter.fillRect(bounds, QColor(TOKENS["hover"] if self.underMouse() else TOKENS["surface"]))
        art_height = 136
        image = self.art.scaled(QSize(self.width(), art_height), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap(QRect(0, 0, self.width(), art_height), image, QRect((image.width() - self.width()) // 2,
                          (image.height() - art_height) // 2, self.width(), art_height))
        painter.setPen(QColor(TOKENS["text"]))
        font = QFont("Bahnschrift")
        font.setPixelSize(TYPE["section"])
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        title = painter.fontMetrics().elidedText(self.instance.name, Qt.TextElideMode.ElideRight, self.width() - 32)
        painter.drawText(QRect(16, art_height + 12, self.width() - 32, 32), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        font.setFamily("Segoe UI")
        font.setPixelSize(TYPE["caption"])
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(TOKENS["muted"]))
        painter.drawText(16, art_height + 63, f"{self.instance.minecraft_version} · {self.instance.loader.title()} · {len(self.instance.installed_mods)} модов")
        played = QDateTime.fromString(self.instance.last_launch, Qt.DateFormat.ISODate)
        last_played = played.toLocalTime().toString("dd.MM.yyyy") if played.isValid() else "Ещё не запускалась"
        font.setPixelSize(TYPE["metadata"])
        painter.setFont(font)
        painter.drawText(16, art_height + 85, f'Память: {self.instance.memory_mb / 1024:g} ГБ · Миры: {self.worlds if self.worlds is not None else "недоступны"}')
        painter.drawText(16, art_height + 105, "Последний запуск: " + last_played)
        state = {"ready": "Готова", "running": "Игра запущена", "error": "Требует внимания"}.get(self.instance.state, self.instance.state)
        painter.drawText(QRect(self.width() - 128, 12, 112, 28), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, state)
        if self.hasFocus() or self.property("selected"):
            painter.setClipping(False)
            painter.setPen(QPen(QColor(TOKENS["accent"]), 2))
            painter.drawPath(path)


class BlankDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        # Native item widgets own the rendering, text is retained for search/a11y.
        pass


class ArtworkGrid(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(BlankDelegate(self))
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setMovement(QListWidget.Movement.Static)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSpacing(12)
        self.setWordWrap(True)
        self.currentItemChanged.connect(self._selection_changed)
        self.setStyleSheet("QListWidget {background:transparent;border:0;padding:0;} QListWidget::item {padding:0;border:0;background:transparent;}")

    def _selection_changed(self, current, previous):
        for item, selected in ((previous, False), (current, True)):
            if item is not None:
                card = self.itemWidget(item)
                if card is not None:
                    card.setProperty("selected", selected)
                    card.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        available = max(280, self.viewport().width() - 24)
        columns = max(1, available // 328)
        width = (available - (columns - 1) * 24) // columns
        self.setGridSize(QSize(width + 24, 340))
        for index in range(self.count()):
            self.item(index).setSizeHint(QSize(width, 316))
