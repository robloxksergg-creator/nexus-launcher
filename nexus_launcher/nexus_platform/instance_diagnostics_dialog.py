"""Explicit read-only diagnosis using the existing instance and dialog owners."""
import threading

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)
from nexus_launcher.instance_diagnostics import scan_instance, redact
from nexus_launcher.themed_dialog import NexusDialog
from nexus_launcher.nexus_platform.presentation_style import stylesheet


class ScanWorker(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, root, loader, parent):
        super().__init__(parent)
        self.root, self.loader = root, loader
        self.cancel = threading.Event()

    def run(self):
        try:
            self.result.emit(scan_instance(self.root, self.loader, self.cancel.is_set))
        except Exception as error:
            # Do not leak raw logs, commands, credentials or exception text.
            self.failed.emit('Не удалось прочитать сборку: ' + type(error).__name__)


class InstanceDiagnosticsDialog(NexusDialog):
    def __init__(self, root, loader, name, parent=None):
        super().__init__(parent)
        self.root, self.loader = root, loader
        self.worker = None
        self.closing = False
        self.report = None
        self.setWindowTitle('Диагностика · ' + name)
        self.setObjectName('platformRoot')
        self.setStyleSheet(stylesheet())
        self.resize(960, 680)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(), int(available.width()*.94)), min(self.height(), int(available.height()*.94)))
        layout = QVBoxLayout(self)
        title = QLabel('Диагностика сборки')
        title.setObjectName('pageTitle')
        layout.addWidget(title)
        copy = QLabel('Локальная проверка метаданных и crash-report. Файлы не меняются, JAR не запускаются, отчёт никуда не отправляется.')
        copy.setWordWrap(True)
        layout.addWidget(copy)
        self.status = QLabel('Нажмите «Проверить сборку».')
        self.status.setWordWrap(True)
        self.status.setAccessibleName('Состояние диагностики')
        layout.addWidget(self.status)
        tabs = QTabWidget()
        layout.addWidget(tabs, 1)
        issues = QSplitter(Qt.Orientation.Horizontal)
        self.findings = QListWidget()
        self.findings.setAccessibleName('Результаты диагностики')
        self.findings.currentRowChanged.connect(self.show_finding)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setAccessibleName('Объяснение и доказательства выбранного результата')
        self.evidence.setPlaceholderText('Здесь будут объяснение, исходные объявления и ограничения проверки.')
        issues.addWidget(self.findings)
        issues.addWidget(self.evidence)
        issues.setSizes([360, 560])
        tabs.addTab(issues, 'Проблемы и доказательства')
        self.dependencies = QTreeWidget()
        self.dependencies.setHeaderLabels(['Мод / обязательная зависимость', 'Объявлено / найдено'])
        self.dependencies.setAccessibleName('Объявленные зависимости включённых модов')
        tabs.addTab(self.dependencies, 'Зависимости')
        actions = QHBoxLayout()
        self.scan = QPushButton('Проверить сборку')
        self.scan.setObjectName('primaryAction')
        self.scan.clicked.connect(self.start_scan)
        actions.addWidget(self.scan)
        actions.addStretch()
        self.close_button = QPushButton('Закрыть')
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)

    def start_scan(self):
        if self.worker is not None:
            return
        self.report = None
        self.findings.clear()
        self.dependencies.clear()
        self.evidence.clear()
        self.status.setText('Читаем метаданные включённых JAR и последний доступный crash-report…')
        self.scan.setEnabled(False)
        worker = ScanWorker(self.root, self.loader, self)
        self.worker = worker
        worker.result.connect(self.show_report)
        worker.failed.connect(self.status.setText)
        worker.finished.connect(self.scan_finished)
        worker.start()

    def show_report(self, report):
        if self.closing:
            return
        self.report = report
        count = sum(f.level != 'info' for f in report.findings)
        self.status.setText(f'Прочитано JAR: {len(report.mods)} · Замечаний: {count} · ' + ('Обход завершён.' if report.complete else 'Отчёт неполный.') + ' Совместимость версий и успешный запуск не подтверждены.')
        levels = {'error': 'Ошибка', 'warning': 'Внимание', 'info': 'Сведения'}
        for finding in report.findings:
            self.findings.addItem(levels[finding.level] + ' · ' + finding.title)
        owners = {}
        for mod in report.mods:
            for identifier in mod.ids:
                owners.setdefault(identifier, []).append(mod.filename)
        implicit = {'minecraft', 'java'} | {'fabric': {'fabricloader'}, 'forge': {'forge'}, 'neoforge': {'neoforge'}}.get(self.loader, set())
        for mod in report.mods:
            parent = QTreeWidgetItem([mod.filename, ', '.join(mod.ids) or 'ID не распознан'])
            self.dependencies.addTopLevelItem(parent)
            for identifier, expression in mod.requires:
                location = 'Компонент среды; версия не проверена' if identifier in implicit else ', '.join(owners.get(identifier, [])) or 'Не найдена / не разрешена'
                QTreeWidgetItem(parent, [identifier + ' · ' + expression, location])
            if mod.nested:
                QTreeWidgetItem(parent, ['Вложенные JAR', 'Не проверены'])
        self.dependencies.resizeColumnToContents(0)
        if self.findings.count():
            self.findings.setCurrentRow(0)

    def show_finding(self, row):
        if self.report is None or not 0 <= row < len(self.report.findings):
            return
        finding = self.report.findings[row]
        self.evidence.setPlainText(redact(finding.title + '\n\n' + finding.detail + '\n\n' + '\n'.join(finding.evidence) + '\n\nКод: ' + finding.code))

    def scan_finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self.scan.setEnabled(True)
        if self.closing:
            super().reject()

    def reject(self):
        if self.worker is not None:
            self.closing = True
            self.worker.cancel.set()
            self.status.setText('Останавливаем чтение…')
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
