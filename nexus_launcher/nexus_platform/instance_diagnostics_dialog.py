"""Explicit read-only diagnosis using the existing instance and dialog owners."""
import threading

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget)
from nexus_launcher.instance_diagnostics import scan_instance, redact
from nexus_launcher.themed_dialog import NexusDialog
from nexus_launcher.nexus_platform.presentation_style import stylesheet
from nexus_launcher.diagnostic_trial import TrialError


class ScanWorker(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, root, loader, parent, operation=None):
        super().__init__(parent)
        self.root, self.loader = root, loader
        self.cancel = threading.Event()
        self.operation = operation

    def run(self):
        try:
            self.result.emit(self.operation(self.cancel.is_set) if self.operation else scan_instance(self.root, self.loader, self.cancel.is_set))
        except Exception as error:
            # Do not leak raw logs, commands, credentials or exception text.
            self.failed.emit(str(error) if isinstance(error, TrialError) else ('Операция не завершена: ' if self.operation else 'Не удалось прочитать сборку: ') + type(error).__name__)


class TrialReviewDialog(NexusDialog):
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Подтвердить диагностическую копию')
        self.setObjectName('platformRoot')
        self.setStyleSheet(stylesheet())
        self.resize(680, 480)
        layout = QVBoxLayout(self)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(
            f'Исходная сборка: {plan.source_root}\n\n'
            f'Новая копия: {plan.trial_name}\nID: {plan.trial_id}\n\n'
            f'Изменение только в копии:\nmods/{plan.filename} → disabled_mods/{plan.filename}\n\n'
            f'Копировать: {len(plan.files)} файлов · {plan.total_bytes/(1024*1024):.1f} МБ\n\n'
            'Копируются игровые моды, настройки и сохранения. Кэш, логи и архивы резервных копий не переносятся. '
            'Исходные файлы не изменяются. Игра не запускается. Зависимые моды могут перестать работать; это пробное изменение, не подтверждённое исправление.\n\n'
            'Закройте Minecraft, включая запущенные отдельно от NEXUS окна. Блокировка охватывает только этот лаунчер. '
            'Сохранения в копии самостоятельны; новые изменения не сливаются с исходной сборкой. '
            'Для возврата выберите исходную сборку. Копию можно удалить позднее через библиотеку.')
        layout.addWidget(details)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton('Отмена')
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setDefault(True)
        self.confirm_button = QPushButton('Создать копию')
        self.confirm_button.clicked.connect(self.accept)
        row.addWidget(self.cancel_button)
        row.addWidget(self.confirm_button)
        layout.addLayout(row)
        self.cancel_button.setFocus()


class InstanceDiagnosticsDialog(NexusDialog):
    def __init__(self, root, loader, name, parent=None, *, trials=None):
        super().__init__(parent)
        self.root, self.loader = root, loader
        self.worker = None
        self.closing = False
        self.report = None
        self.trials = trials
        self.pending_plan = None
        self.review_dialog = None
        self.trial_result = None
        self.selected_instance_id = ''
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
        copy = QLabel('Проверка читает метаданные и crash-report, без запуска JAR и отправки отчёта. ' + ('Пробное изменение создаётся отдельно после подтверждения.' if trials else 'Изменения этой сборки здесь недоступны.'))
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
        self.findings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.findings.setTextElideMode(Qt.TextElideMode.ElideRight)
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
        trial_actions = QHBoxLayout()
        self.prepare_trial = QPushButton('Подготовить копию без выбранного мода…')
        self.prepare_trial.setVisible(trials is not None)
        self.prepare_trial.setEnabled(False)
        self.prepare_trial.clicked.connect(self.prepare_copy)
        trial_actions.addWidget(self.prepare_trial)
        self.open_trial = QPushButton('Открыть копию')
        self.open_original = QPushButton('Вернуться к исходной сборке')
        self.open_trial.hide()
        self.open_original.hide()
        self.open_trial.clicked.connect(lambda: self.choose_instance(self.trial_result.trial_id))
        self.open_original.clicked.connect(lambda: self.choose_instance(self.trial_result.source_id))
        trial_actions.addWidget(self.open_trial)
        trial_actions.addWidget(self.open_original)
        trial_actions.addStretch()
        layout.addLayout(trial_actions)
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
        if self.worker is not None or self.review_dialog is not None:
            return
        self.report = None
        self.findings.clear()
        self.dependencies.clear()
        self.evidence.clear()
        self.status.setText('Читаем метаданные включённых JAR и последний доступный crash-report…')
        self.scan.setEnabled(False)
        self.refresh_trial_actions()
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
            self.findings.item(self.findings.count()-1).setToolTip(redact(finding.title))
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
        self.refresh_trial_actions()

    def refresh_trial_actions(self):
        row = self.findings.currentRow()
        filename = self.report.findings[row].filename if self.report and 0 <= row < len(self.report.findings) else ''
        busy = self.worker is not None or self.review_dialog is not None
        self.prepare_trial.setEnabled(bool(self.trials and filename and not busy and not self.trial_result))
        self.open_trial.setEnabled(not busy)
        self.open_original.setEnabled(not busy)

    def start_operation(self, operation, result_handler, message):
        if self.worker is not None:
            return
        self.scan.setEnabled(False)
        self.status.setText(message)
        worker = ScanWorker(self.root, self.loader, self, operation)
        self.worker = worker
        worker.result.connect(result_handler)
        worker.failed.connect(self.status.setText)
        worker.finished.connect(self.scan_finished)
        self.refresh_trial_actions()
        worker.start()

    def prepare_copy(self):
        row = self.findings.currentRow()
        if self.trials is None or self.report is None or not 0 <= row < len(self.report.findings):
            return
        filename = self.report.findings[row].filename
        if not filename or self.trial_result:
            return
        self.start_operation(lambda cancelled: self.trials.prepare(filename, cancelled), self.copy_prepared,
                             'Подготавливаем точный план и проверяем игровые файлы…')

    def copy_prepared(self, plan):
        self.pending_plan = plan

    def review_trial(self, plan):
        dialog = TrialReviewDialog(plan, self)
        self.review_dialog = dialog
        dialog.finished.connect(lambda result: self.review_closed(dialog, plan, result))
        self.refresh_trial_actions()
        dialog.open()

    def review_closed(self, dialog, plan, result):
        self.review_dialog = None
        dialog.deleteLater()
        if self.closing:
            return
        if result == NexusDialog.DialogCode.Accepted:
            self.start_operation(lambda cancelled: self.trials.apply(plan, cancelled), self.copy_created,
                                 'Создаём и проверяем отдельную диагностическую копию…')
        else:
            self.status.setText('Создание копии отменено. Исходные файлы не менялись.')
            self.refresh_trial_actions()

    def copy_created(self, result):
        self.trial_result = result
        self.status.setText('Копия создана: ' + result.trial_name + '. Выбранный мод отключён только в ней. Игра не запускалась; исправление ещё не подтверждено.')
        self.open_trial.show()
        self.open_original.show()

    def choose_instance(self, identifier):
        if self.worker is None:
            self.selected_instance_id = identifier
            self.accept()

    def scan_finished(self):
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()
        self.scan.setEnabled(True)
        self.refresh_trial_actions()
        if self.closing:
            super().reject()
        elif self.pending_plan is not None:
            plan, self.pending_plan = self.pending_plan, None
            self.review_trial(plan)

    def reject(self):
        if self.review_dialog is not None:
            self.closing = True
            self.review_dialog.reject()
        if self.worker is not None:
            self.closing = True
            self.worker.cancel.set()
            self.status.setText('Завершаем текущий шаг и отменяем дальнейшие действия…')
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
