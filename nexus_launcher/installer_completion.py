"""Post-install presentation. Actions remain owned by the installer window."""
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QRectF, QByteArray, Signal, QPointF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QIcon, QPen, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton,
                              QScrollArea, QVBoxLayout, QWidget, QStyle, QStyleOptionButton)
from nexus_launcher.themed_dialog import NexusDialog
from nexus_launcher.nexus_platform.presentation_style import stylesheet
from nexus_launcher.online_installation import InstallationDetails


def mark_path():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return root / 'assets' / 'nexus-mark.svg'


class Backdrop(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mark = QSvgRenderer(QByteArray(mark_path().read_bytes()), self)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        background = QLinearGradient(0, 0, w, h)
        background.setColorAt(0, QColor('#07111e'))
        background.setColorAt(.55, QColor('#10243b'))
        background.setColorAt(1, QColor('#080e17'))
        p.fillRect(self.rect(), background)
        for offset, opacity in [(0, 65), (95, 30)]:
            wave = QPainterPath()
            wave.moveTo(-80, h * .47 + offset)
            wave.cubicTo(w * .23, h * .45, w * .28, -90, w * .77, 45 + offset)
            wave.cubicTo(w * .9, 90, w * .94, -40, w + 80, -60)
            wave.lineTo(w + 80, 130)
            wave.cubicTo(w * .62, 10, w * .33, h * .7, -80, h * .63 + offset)
            wave.closeSubpath()
            sheen = QLinearGradient(0, 0, w, h)
            sheen.setColorAt(0, QColor(46, 145, 232, opacity))
            sheen.setColorAt(.6, QColor(7, 17, 30, 10))
            p.fillPath(wave, sheen)
        p.setOpacity(.12)
        self.mark.render(p, QRectF(w * .68, 14, w * .33, w * .23))
        p.end()


class TickBox(QCheckBox):
    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            option = QStyleOptionButton()
            self.initStyleOption(option)
            rect = self.style().subElementRect(QStyle.SubElement.SE_CheckBoxIndicator, option, self)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setPen(QPen(QColor('#09243b'), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPolyline(QPolygonF([QPointF(rect.left()+5, rect.center().y()), QPointF(rect.left()+9, rect.bottom()-5), QPointF(rect.right()-4, rect.top()+5)]))
            p.end()


class CompletionWindow(NexusDialog):
    launch_requested = Signal(bool)
    finish_requested = Signal(bool, bool)
    folder_requested = Signal()
    licenses_requested = Signal()

    def __init__(self, details: InstallationDetails, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Установка NEXUS Launcher')
        self.setWindowIcon(QIcon(str(mark_path())))
        self.setMinimumSize(560, 440)
        self.resize(1040, 780)
        self.setStyleSheet(stylesheet() + '''
            QDialog {background:#080e17;}
            QScrollArea, QScrollArea>QWidget>QWidget {background:transparent;border:0;}
            QFrame#installSummary {background:rgba(16,29,46,215);border:1px solid #30485f;border-radius:18px;}
            QLabel#completeTitle {font-size:36px;font-weight:700;color:#f0f6ff;}
            QLabel#completeLead {font-size:17px;color:#cbdced;}
            QLabel#summaryCaption {font-size:14px;font-weight:600;color:#afd9fb;}
            QLabel#summaryValue {font-size:15px;color:#e0eaf6;}
            QLabel#verificationValue {color:#60deb0;font-size:15px;}
            QPushButton#completeLaunch {background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #85ceff,stop:1 #4d94ef);color:#071a2b;border:1px solid #9bdeff;border-radius:13px;min-height:40px;font-size:19px;font-weight:700;}
            QPushButton#completeLaunch:hover {background:#99d7ff;}
            QPushButton#completeLaunch:focus {border:2px solid white;}
            QPushButton#completeDone {background:#142439;border:1px solid #30485f;border-radius:12px;min-height:34px;font-size:16px;}
            QCheckBox {font-size:14px;spacing:9px;}
            QCheckBox::indicator {width:20px;height:20px;border:1px solid #5a809f;border-radius:5px;background:#0c1725;}
            QCheckBox::indicator:checked {background:#79c8ff;border:2px solid #d4f1ff;}
        ''')
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        surface = Backdrop()
        content = QVBoxLayout(surface)
        content.setContentsMargins(40, 24, 40, 20)
        content.setSpacing(12)
        content.addStretch()
        check = QLabel('✓')
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check.setFixedSize(70, 70)
        check.setStyleSheet('color:#8cdaff;font-size:50px;background:#152d47;border:2px solid #74bbeb;border-radius:20px;')
        content.addWidget(check, 0, Qt.AlignmentFlag.AlignHCenter)
        title = QLabel('Установка завершена!')
        title.setObjectName('completeTitle')
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)
        lead = QLabel('NEXUS Launcher установлен на ваш компьютер.')
        lead.setObjectName('completeLead')
        lead.setWordWrap(True)
        lead.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(lead)
        summary = QFrame()
        summary.setObjectName('installSummary')
        box = QVBoxLayout(summary)
        box.setContentsMargins(20, 16, 20, 16)
        box.setSpacing(8)
        caption = QLabel('Папка установки')
        caption.setObjectName('summaryCaption')
        caption_row = QHBoxLayout()
        caption_row.addWidget(caption)
        open_folder = QPushButton('Открыть папку ↗')
        open_folder.clicked.connect(self.folder_requested)
        caption_row.addWidget(open_folder)
        box.addLayout(caption_row)
        self.location = QLabel(str(details.executable.parent))
        self.location.setTextFormat(Qt.TextFormat.PlainText)
        self.location.setObjectName('summaryValue')
        self.location.setWordWrap(True)
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.location)
        self.version = QLabel('Версия  ' + details.version)
        self.version.setObjectName('summaryValue')
        box.addWidget(self.version)
        self.verification = QLabel('✓ Подпись пакета и целостность файлов проверены')
        self.verification.setObjectName('verificationValue')
        self.verification.setWordWrap(True)
        box.addWidget(self.verification)
        size = QLabel(f'{details.file_count:,} файлов · {details.total_bytes / (1024 * 1024):.1f} МБ')
        size.setObjectName('summaryValue')
        box.addWidget(size)
        content.addWidget(summary)
        actions_panel = QWidget()
        actions_panel.setObjectName('completeActions')
        actions_panel.setStyleSheet('QWidget#completeActions {background:#0d1b2b;}')
        actions = QVBoxLayout(actions_panel)
        actions.setContentsMargins(40, 14, 40, 16)
        actions.setSpacing(10)
        self.launch_check = TickBox('Запустить NEXUS Launcher после завершения')
        self.launch_check.setChecked(True)
        self.shortcut_check = TickBox('Создать ярлык на рабочем столе')
        actions.addWidget(self.launch_check)
        actions.addWidget(self.shortcut_check)
        self.error = QLabel('')
        self.error.setWordWrap(True)
        self.error.setStyleSheet('color:#ffb6be;')
        self.error.hide()
        actions.addWidget(self.error)
        self.launch = QPushButton('▶  Запустить NEXUS')
        self.launch.setObjectName('completeLaunch')
        self.launch.clicked.connect(lambda: self.launch_requested.emit(self.shortcut_check.isChecked()))
        self.done_button = QPushButton('Готово')
        self.done_button.setObjectName('completeDone')
        self.done_button.clicked.connect(lambda: self.finish_requested.emit(self.launch_check.isChecked(), self.shortcut_check.isChecked()))
        for button in (self.launch, self.done_button):
            button.setMaximumWidth(560)
            row = QHBoxLayout()
            row.addStretch(1)
            row.addWidget(button, 10)
            row.addStretch(1)
            actions.addLayout(row)
        content.addStretch()
        footer = QLabel('NEXUS Launcher  ·  ForceCore Production  ·  GPL-3.0-only')
        footer.setWordWrap(True)
        footer.setStyleSheet('color:#a7bbd1;font-size:12px;')
        footer_row = QHBoxLayout()
        footer_row.addWidget(footer, 1)
        licenses = QPushButton('Лицензии компонентов ↗')
        licenses.clicked.connect(self.licenses_requested)
        footer_row.addWidget(licenses)
        actions.addLayout(footer_row)
        self.licenses_button = licenses
        scroll.setWidget(surface)
        outer.addWidget(scroll, 1)
        outer.addWidget(actions_panel)

    def showEvent(self, event):
        super().showEvent(event)
        if hasattr(self, 'title_bar'):
            self.title_bar.minimize.show()

    def show_error(self, text):
        self.error.setText(text)
        self.error.show()

    def set_busy(self, busy):
        self.launch.setEnabled(not busy)
        self.done_button.setEnabled(not busy)
        self.shortcut_check.setEnabled(not busy)
        self.launch_check.setEnabled(not busy)
