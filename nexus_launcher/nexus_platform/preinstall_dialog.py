"""Native preparation report. No download, launch or admission capability."""
import threading
from datetime import datetime
from PySide6.QtCore import QThread, Signal, Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QColor
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget
from nexus_launcher.preinstall_check import collect
from nexus_launcher.themed_dialog import NexusDialog
from .presentation_style import stylesheet
from .theme_tokens import TOKENS

SCAN_ACCENT = '#35c8df'  # Owner-selected diagnostic accent; shared buttons/theme remain canonical.
SYSTEM_HEADINGS = ('Оперативная память','Место для установки','Java Runtime','Связь с сервером','FPS и скорость загрузки')
STATE_LABELS = {'ok':'ПРОВЕРЕНО','info':'СВЕДЕНИЯ','warning':'ОБРАТИТЕ ВНИМАНИЕ','unknown':'НЕ ПОДТВЕРЖДЕНО'}
STATE_COLORS = {'ok':TOKENS['success'], 'warning':TOKENS['warning'], 'info':TOKENS['accent'], 'unknown':TOKENS['muted'], 'brand':SCAN_ACCENT}


def report_style():
    return f"""
    QFrame#preinstallCard {{ background:{TOKENS['sidebar']}; border:1px solid {TOKENS['border']}; border-radius:8px; }}
    QLabel#scanBrand {{ font-size:14px; font-weight:700; color:{TOKENS['text']}; }}
    QLabel#scanCaption, QLabel#probeDetails {{ font-size:12px; color:{TOKENS['muted']}; }}
    QLabel#scanBadge {{ background:{TOKENS['surface']}; color:{SCAN_ACCENT}; border-radius:8px; padding:5px 9px; font-size:11px; }}
    QLabel#scanTitle {{ font-size:25px; font-weight:650; color:{TOKENS['text']}; }}
    QLabel#probeHeading {{ font-size:14px; font-weight:650; color:{TOKENS['text']}; }}
    QLabel#probeNumber {{ color:{SCAN_ACCENT}; font-size:12px; }}
    QLabel#probeValue {{ font-size:13px; }}
    QFrame#scanDivider, QFrame#probeRail {{ background:{TOKENS['border']}; border:0; }}
    QProgressBar#scanProgress {{ border:0; background:{TOKENS['border']}; min-height:3px; max-height:3px; }}
    QProgressBar#scanProgress::chunk {{ background:{SCAN_ACCENT}; }}
    """


class ProbeIcon(QWidget):
    """Small vector status symbol; no icon-font dependency or color-only meaning."""
    def __init__(self, state='unknown', parent=None):
        super().__init__(parent); self.state=state; self.setFixedSize(18,18)
    def set_state(self,state):
        self.state=state; self.setAccessibleName(STATE_LABELS.get(state,'Диагностика')); self.update()
    def paintEvent(self,event):
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width()/20,self.height()/20)
        pen=QPen(QColor(STATE_COLORS[self.state])); pen.setWidthF(1.4); painter.setPen(pen); painter.setBrush(Qt.BrushStyle.NoBrush)
        path=QPainterPath()
        if self.state=='brand':
            painter.drawRoundedRect(QRectF(3,3,14,14),2,2);path.moveTo(5,10);path.lineTo(8,10);path.lineTo(10,6);path.lineTo(12,13);path.lineTo(15,10);painter.drawPath(path)
        elif self.state=='warning':
            path.moveTo(10,3);path.lineTo(18,17);path.lineTo(2,17);path.closeSubpath();painter.drawPath(path);painter.drawLine(QPointF(10,8),QPointF(10,11));painter.drawPoint(QPointF(10,14))
        else:
            painter.drawEllipse(QRectF(3,3,14,14))
            if self.state=='ok':path.moveTo(6,10);path.lineTo(9,13);path.lineTo(14,7);painter.drawPath(path)
            else:painter.drawText(QRectF(3,2,14,15),Qt.AlignmentFlag.AlignCenter,'i' if self.state=='info' else '?')
        painter.end()


class CheckWorker(QThread):
    result = Signal(object)
    failed = Signal()
    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.cancel = threading.Event()
    def run(self):
        try: self.result.emit(self.operation(self.cancel.is_set))
        except Exception: self.failed.emit()  # Never expose paths, commands or raw errors.

class PreinstallDialog(NexusDialog):
    def __init__(self, server, storage_root, *, java_path='', allocated_mb=4096, parent=None, operation=None):
        super().__init__(parent)
        self.setWindowTitle('Проверить перед установкой')
        self.setObjectName('platformRoot'); self.setStyleSheet(stylesheet()+report_style())
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(920, int(screen.width()*.94)), min(740, int(screen.height()*.94)))
        self.worker = None; self.closing = False; self._source_mode = False
        self.operation = operation or (lambda cancelled: collect(server, storage_root, java_path=java_path, allocated_mb=allocated_mb, cancelled=cancelled))
        root = QVBoxLayout(self); root.setContentsMargins(20,16,20,16); root.setSpacing(12)
        brand=QHBoxLayout(); brand.setSpacing(10); brand.addWidget(ProbeIcon('brand'))
        identity=QVBoxLayout(); identity.setSpacing(2)
        brand_title=QLabel('NEXUS / DIAGNOSTICS'); brand_title.setObjectName('scanBrand')
        caption=QLabel('ПРОВЕРКА ПЕРЕД УСТАНОВКОЙ'); caption.setObjectName('scanCaption')
        identity.addWidget(brand_title);identity.addWidget(caption);brand.addLayout(identity,1)
        self.scan_badge=QLabel('ОЖИДАНИЕ');self.scan_badge.setObjectName('scanBadge');brand.addWidget(self.scan_badge)
        root.addLayout(brand)
        def divider():
            line=QFrame();line.setObjectName('scanDivider');line.setFixedHeight(1);return line
        accent_line=divider();accent_line.setStyleSheet('background:'+SCAN_ACCENT);root.addWidget(accent_line)
        title = QLabel('Проверим перед скачиванием'); title.setObjectName('scanTitle'); title.setWordWrap(True); root.addWidget(title)
        name = QLabel(server.name); name.setTextFormat(Qt.TextFormat.PlainText); name.setWordWrap(True); name.setObjectName('muted'); root.addWidget(name)
        self.progress = QProgressBar(); self.progress.setObjectName('scanProgress'); self.progress.setTextVisible(False); self.progress.setRange(0,0); self.progress.hide(); root.addWidget(self.progress)
        self.status = QLabel('Нажмите «Начать проверку». Это предварительный отчёт, не допуск к серверу и не прогноз FPS.')
        self.status.setObjectName('scanCaption');self.status.setWordWrap(True); root.addWidget(self.status)
        root.addWidget(divider())
        self.section_heading=QLabel('КОМПОНЕНТЫ СИСТЕМЫ');self.section_heading.setObjectName('probeHeading');root.addWidget(self.section_heading)
        scroll = QScrollArea(); self.scroll=scroll; scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(); self.cards = QVBoxLayout(content); self.cards.setContentsMargins(0,0,0,0); self.cards.setSpacing(12); self.cards.addStretch()
        scroll.setWidget(content); root.addWidget(scroll,1)
        self.labels, self.details, self.icons, self.headings = [], [], [], []
        for number, heading in enumerate(SYSTEM_HEADINGS,1):
            item=QWidget();row_layout=QHBoxLayout(item);row_layout.setContentsMargins(0,0,0,0);row_layout.setSpacing(12)
            timeline=QVBoxLayout();timeline.setSpacing(6)
            number_label=QLabel(f'{number:02}');number_label.setObjectName('probeNumber');number_label.setAlignment(Qt.AlignmentFlag.AlignHCenter);timeline.addWidget(number_label)
            rail=QFrame();rail.setObjectName('probeRail');rail.setFixedWidth(1);timeline.addWidget(rail,1,Qt.AlignmentFlag.AlignHCenter);row_layout.addLayout(timeline)
            frame = QFrame(); frame.setObjectName('preinstallCard'); layout = QVBoxLayout(frame); layout.setContentsMargins(14,12,14,12);layout.setSpacing(6)
            heading_label = QLabel(heading); heading_label.setObjectName('probeHeading'); heading_label.setWordWrap(True); layout.addWidget(heading_label)
            self.headings.append(heading_label)
            value_row=QHBoxLayout();value_row.setSpacing(6);icon=ProbeIcon();value_row.addWidget(icon,0,Qt.AlignmentFlag.AlignTop)
            detail = QLabel('Не измерено');detail.setObjectName('probeValue'); detail.setTextFormat(Qt.TextFormat.PlainText); detail.setWordWrap(True);detail.setStyleSheet('color:'+TOKENS['muted']); detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse);value_row.addWidget(detail,1);layout.addLayout(value_row)
            explanation=QLabel('');explanation.setObjectName('probeDetails');explanation.setTextFormat(Qt.TextFormat.PlainText);explanation.setWordWrap(True);explanation.hide();layout.addWidget(explanation)
            row_layout.addWidget(frame,1);self.cards.insertWidget(self.cards.count()-1,item)
            self.labels.append(detail);self.details.append(explanation);self.icons.append(icon)
        note=QLabel('Без запуска игры и установки. Java проверяется через -version; неизвестные данные не считаются успешной проверкой.')
        self.note = note
        note.setObjectName('scanCaption');note.setWordWrap(True);root.addWidget(note)
        root.addWidget(divider())
        row = QHBoxLayout(); row.addStretch()
        self.sources_button = QPushButton('Источники загрузки')
        def check_sources():
            from nexus_launcher.download_sources import collect_sources, sources
            if self.worker is not None: return
            for label, source in zip(self.headings, sources(getattr(server, 'loader', 'neoforge'))):
                label.setText(source.name)
            self.start(lambda cancelled: collect_sources(server, cancelled=cancelled))
        self.sources_button.clicked.connect(check_sources)
        self.start_button = QPushButton('Начать проверку'); self.start_button.setObjectName('primaryAction'); self.start_button.clicked.connect(self.start)
        self.close_button = QPushButton('Закрыть'); self.close_button.clicked.connect(self.reject)
        root.addWidget(self.sources_button)
        row.addWidget(self.close_button); row.addWidget(self.start_button); root.addLayout(row)
    def start(self, operation=None):
        if self.worker is not None: return
        self.closing = False
        self._source_mode = callable(operation)
        if not self._source_mode:
            for label, title in zip(self.headings, SYSTEM_HEADINGS): label.setText(title)
        self.section_heading.setText('ИСТОЧНИКИ ЗАГРУЗКИ' if self._source_mode else 'КОМПОНЕНТЫ СИСТЕМЫ')
        self.note.setText('Без входа в аккаунт и скачивания файлов. Ответ относится к проверенному адресу, а не ко всем файлам источника.' if self._source_mode else 'Без запуска игры и установки. Java проверяется через -version; неизвестные данные не считаются успешной проверкой.')
        for label, explanation, icon in zip(self.labels,self.details,self.icons):
            label.setText('Проверяется…');label.setStyleSheet('color:'+TOKENS['muted']);explanation.clear();explanation.hide();icon.set_state('unknown')
        self.scan_badge.setText('СКАНИРОВАНИЕ')
        self.status.setText('Проверка выполняется в фоне. Можно отменить; текущий системный запрос должен завершиться.')
        self.start_button.setEnabled(False); self.sources_button.setEnabled(False); self.progress.show(); self.close_button.setText('Отменить')
        self.worker = CheckWorker(operation if callable(operation) else self.operation,self)
        self.worker.result.connect(self.received); self.worker.failed.connect(self.failed); self.worker.finished.connect(self._worker_finished)
        self.worker.start()
    def received(self, report):
        if self.closing: return
        for index, item in enumerate(report.checks[:len(self.labels)]):
            self.headings[index].setText(item.title)
            main, separator, explanation = item.detail.partition('. ')
            self.labels[index].setText(STATE_LABELS[item.state]+' · '+main+('.' if separator else ''))
            self.labels[index].setStyleSheet('color:'+STATE_COLORS[item.state]);self.icons[index].set_state(item.state)
            self.details[index].setText(explanation);self.details[index].setVisible(bool(explanation))
        for index in range(len(report.checks),len(self.labels)):
            self.labels[index].setText('Не измерено');self.labels[index].setStyleSheet('color:'+TOKENS['muted']);self.details[index].hide();self.icons[index].set_state('unknown')
        self.scan_badge.setText('ОТМЕНЕНО' if report.cancelled else f'ОБРАБОТАНО {len(report.checks)}/{len(self.labels)}')
        stamp = datetime.fromtimestamp(report.measured_at).strftime('%H:%M:%S')
        self.status.setText(('Проверка отменена. ' if report.cancelled else 'Предварительная проверка завершена. ')+f'Снимок состояния: {stamp}. Неизвестные показатели не считаются успешной проверкой.')
    def failed(self):
        if self.closing: return
        self.scan_badge.setText('ПРЕРВАНО')
        for label,explanation,icon in zip(self.labels,self.details,self.icons):
            label.setText('Не подтверждено — проверка прервана');label.setStyleSheet('color:'+TOKENS['muted']);explanation.hide();icon.set_state('unknown')
        self.status.setText('Не удалось завершить проверку. Ничего не устанавливалось. Можно повторить вручную.')
    def _worker_finished(self):
        worker = self.worker; self.worker = None
        if worker: worker.deleteLater()
        self.progress.hide(); self.start_button.setEnabled(True); self.sources_button.setEnabled(True); self.start_button.setText('Проверить компьютер' if self._source_mode else 'Проверить ещё раз'); self.close_button.setText('Закрыть')
        if self.closing: super().reject()
    def reject(self):
        if self.worker is not None:
            self.closing = True; self.worker.cancel.set(); self.scan_badge.setText('ОТМЕНА')
            self.status.setText('Отмена запрошена. Дождитесь завершения текущего системного запроса.')
            return
        super().reject()
    def closeEvent(self,event):
        if self.worker is not None:
            self.reject(); event.ignore(); return
        super().closeEvent(event)
