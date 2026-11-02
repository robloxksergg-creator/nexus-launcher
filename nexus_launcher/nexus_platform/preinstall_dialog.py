"""Native preparation report. No download, launch or admission capability."""
import threading
from datetime import datetime
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget
from nexus_launcher.preinstall_check import collect
from nexus_launcher.themed_dialog import NexusDialog
from .presentation_style import stylesheet

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
        self.setObjectName('platformRoot'); self.setStyleSheet(stylesheet())
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(920, int(screen.width()*.94)), min(740, int(screen.height()*.94)))
        self.worker = None; self.closing = False
        self.operation = operation or (lambda cancelled: collect(server, storage_root, java_path=java_path, allocated_mb=allocated_mb, cancelled=cancelled))
        root = QVBoxLayout(self); root.setContentsMargins(24,20,24,20); root.setSpacing(12)
        title = QLabel('Проверим перед скачиванием'); title.setObjectName('dialogTitle'); title.setWordWrap(True); root.addWidget(title)
        name = QLabel(server.name); name.setTextFormat(Qt.TextFormat.PlainText); name.setWordWrap(True); root.addWidget(name)
        intro = QLabel('RAM, диск, Java и соединение только с выбранным сервером. Java проверяется через -version. Игра не запускается; установка и настройки не изменяются.')
        intro.setWordWrap(True); intro.setObjectName('muted'); root.addWidget(intro)
        self.status = QLabel('Нажмите «Начать проверку». Результат не даёт допуск к серверу и не гарантирует производительность.')
        self.status.setWordWrap(True); root.addWidget(self.status)
        self.progress = QProgressBar(); self.progress.setRange(0,0); self.progress.hide(); root.addWidget(self.progress)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget(); self.cards = QVBoxLayout(content); self.cards.setContentsMargins(0,0,0,0); self.cards.setSpacing(12); self.cards.addStretch()
        scroll.setWidget(content); root.addWidget(scroll,1)
        self.labels = []
        for heading in ['Оперативная память','Место для установки','Java','Связь с сервером','FPS и скорость загрузки']:
            frame = QFrame(); frame.setObjectName('contentCard'); layout = QVBoxLayout(frame); layout.setContentsMargins(16,12,16,12)
            caption = QLabel(heading); caption.setWordWrap(True); layout.addWidget(caption)
            detail = QLabel('Не измерено'); detail.setTextFormat(Qt.TextFormat.PlainText); detail.setWordWrap(True); detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); layout.addWidget(detail)
            self.cards.insertWidget(self.cards.count()-1,frame); self.labels.append(detail)
        row = QHBoxLayout(); row.addStretch()
        self.start_button = QPushButton('Начать проверку'); self.start_button.setObjectName('primaryAction'); self.start_button.clicked.connect(self.start)
        self.close_button = QPushButton('Закрыть'); self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button); row.addWidget(self.start_button); root.addLayout(row)
    def start(self):
        if self.worker is not None: return
        self.closing = False
        for label in self.labels: label.setText('Проверяется…')
        self.status.setText('Проверка выполняется в фоне. Можно отменить; текущий системный запрос должен завершиться.')
        self.start_button.setEnabled(False); self.progress.show(); self.close_button.setText('Отменить')
        self.worker = CheckWorker(self.operation,self)
        self.worker.result.connect(self.received); self.worker.failed.connect(self.failed); self.worker.finished.connect(self._worker_finished)
        self.worker.start()
    def received(self, report):
        if self.closing: return
        labels = {'ok':'ПРОВЕРЕНО','info':'СВЕДЕНИЯ','warning':'ОБРАТИТЕ ВНИМАНИЕ','unknown':'НЕ ПОДТВЕРЖДЕНО'}
        for widget, item in zip(self.labels,report.checks): widget.setText(labels[item.state]+' · '+item.detail)
        for widget in self.labels[len(report.checks):]: widget.setText('Не измерено')
        stamp = datetime.fromtimestamp(report.measured_at).strftime('%H:%M:%S')
        self.status.setText(('Проверка отменена. ' if report.cancelled else 'Предварительная проверка завершена. ')+f'Снимок состояния: {stamp}. Неизвестные показатели не считаются успешной проверкой.')
    def failed(self):
        if self.closing: return
        for label in self.labels: label.setText('Не подтверждено — проверка прервана')
        self.status.setText('Не удалось завершить проверку. Ничего не устанавливалось. Можно повторить вручную.')
    def _worker_finished(self):
        worker = self.worker; self.worker = None
        if worker: worker.deleteLater()
        self.progress.hide(); self.start_button.setEnabled(True); self.start_button.setText('Проверить ещё раз'); self.close_button.setText('Закрыть')
        if self.closing: super().reject()
    def reject(self):
        if self.worker is not None:
            self.closing = True; self.worker.cancel.set()
            self.status.setText('Отмена запрошена. Дождитесь завершения текущего системного запроса.')
            return
        super().reject()
    def closeEvent(self,event):
        if self.worker is not None:
            self.reject(); event.ignore(); return
        super().closeEvent(event)
