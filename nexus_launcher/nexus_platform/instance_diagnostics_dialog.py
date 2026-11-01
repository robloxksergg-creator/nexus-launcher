"""Explicit read-only diagnosis using the existing instance and dialog owners."""
import threading

from PySide6.QtCore import QThread, Signal, Qt, QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QPushButton, QSplitter, QTabWidget, QTreeWidget, QFrame, QListWidgetItem, QProgressBar,
    QTreeWidgetItem, QVBoxLayout, QWidget, QHeaderView)
from nexus_launcher.instance_diagnostics import scan_instance, redact
from nexus_launcher.themed_dialog import NexusDialog
from nexus_launcher.nexus_platform.presentation_style import stylesheet
from nexus_launcher.diagnostic_trial import TrialError
from nexus_launcher.nexus_platform.theme_tokens import TOKENS


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
        self.resize(740, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        eyebrow = QLabel('ПРОБНОЕ ИЗМЕНЕНИЕ  /  ОТДЕЛЬНАЯ КОПИЯ')
        eyebrow.setObjectName('eyebrow')
        title = QLabel('Проверим без одного мода')
        title.setObjectName('dialogTitle')
        title.setWordWrap(True)
        caption = QLabel('Исходная сборка останется на месте. Проверьте план перед созданием копии.')
        caption.setObjectName('muted')
        caption.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(caption)
        details = QPlainTextEdit()
        details.setReadOnly(True)
        details.setPlainText(
            f'Исходная сборка: {plan.source_root}\n\n'
            f'Новая копия: {plan.trial_name}\nПапка: {plan.target_root}\n\n'
            f'Изменение только в копии:\nmods/{plan.filename} → disabled_mods/{plan.filename}\n\n'
            f'Файлов: {len(plan.files)} · Объём: {plan.total_bytes:,} байт ({plan.total_bytes/(1024*1024):.1f} МиБ)\n\n'
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
        self.confirm_button.setObjectName('primaryAction')
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
        self.resize(1080, 760)
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(self.width(), int(available.width()*.94)), min(self.height(), int(available.height()*.94)))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.workspace_layout = layout
        eyebrow = QLabel('NEXUS  /  СОСТОЯНИЕ СБОРКИ')
        self.workspace_eyebrow = eyebrow
        eyebrow.setObjectName('eyebrow')
        layout.addWidget(eyebrow)
        title = QLabel('Центр диагностики')
        self.workspace_title = title
        title.setObjectName('dialogTitle')
        layout.addWidget(title)
        context = QLabel(name + '  ·  ' + loader.capitalize())
        context.setTextFormat(Qt.TextFormat.PlainText)
        context.setObjectName('muted')
        context.setWordWrap(True)
        context.setMaximumHeight(44)
        context.setToolTip(name)
        layout.addWidget(context)
        summary = QHBoxLayout()
        summary.setSpacing(12)
        self.summary_values = []
        self.summary_cards = []
        for caption, tone in [('JAR прочитано', 'accent'), ('Замечания', 'warning'), ('Условия не проверены', 'muted')]:
            card = QFrame()
            card.setObjectName('diagnosticMetric')
            self.summary_cards.append(card)
            cell = QVBoxLayout(card)
            cell.setContentsMargins(16, 10, 16, 10)
            value = QLabel('—')
            value.setObjectName('diagnosticNumber')
            value.setProperty('tone', tone)
            label = QLabel(caption)
            label.setObjectName('muted')
            label.setWordWrap(True)
            cell.addWidget(value)
            cell.addWidget(label)
            summary.addWidget(card, 1)
            self.summary_values.append(value)
        layout.addLayout(summary)
        self.status = QLabel('Начните проверку, чтобы увидеть замечания и их источники.')
        self.status.setObjectName('diagnosticStatus')
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(40)
        self.status.setAccessibleName('Состояние диагностики')
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setAccessibleName('Ход диагностики')
        layout.addWidget(self.progress)
        tabs = QTabWidget()
        self.tabs = tabs
        layout.addWidget(tabs, 1)
        issues = QSplitter(Qt.Orientation.Horizontal)
        self.issues_splitter = issues
        issues.setObjectName('diagnosticSplitter')
        issues.setChildrenCollapsible(False)
        issues.setHandleWidth(12)
        self.findings = QListWidget()
        self.findings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.findings.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.findings.setAccessibleName('Результаты диагностики')
        self.findings.currentRowChanged.connect(self.show_finding)
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        self.evidence.setAccessibleName('Объяснение и доказательства выбранного результата')
        self.evidence.setPlaceholderText('Здесь будут объяснение, исходные объявления и ограничения проверки.')
        self.findings.setMinimumHeight(108)
        self.findings.setObjectName('diagnosticFindings')
        self.findings.setSpacing(4)
        details = QWidget()
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(12, 8, 0, 0)
        detail_layout.setSpacing(8)
        self.detail_kind = QLabel('ОБЪЯСНЕНИЕ И ИСТОЧНИК')
        self.detail_kind.setObjectName('eyebrow')
        self.detail_title = QLabel('Выберите результат проверки')
        self.detail_title.setObjectName('cardTitle')
        self.detail_title.setWordWrap(True)
        self.detail_title.setTextFormat(Qt.TextFormat.PlainText)
        detail_layout.addWidget(self.detail_kind)
        detail_layout.addWidget(self.detail_title)
        detail_layout.addWidget(self.evidence, 1)
        self.evidence.setObjectName('diagnosticEvidence')
        issues.addWidget(self.findings)
        issues.addWidget(details)
        issues.setSizes([360, 560])
        tabs.addTab(issues, 'Проблемы и доказательства')
        self.dependencies = QTreeWidget()
        self.dependencies.setAlternatingRowColors(False)
        self.dependencies.setIndentation(18)
        self.dependencies.setUniformRowHeights(True)
        self.dependencies.setMinimumWidth(0)
        self.dependencies.setHeaderLabels(['Мод / зависимость', 'Требуется / объявлено', 'Условие версии'])
        self.dependencies.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.dependencies.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.dependencies.setColumnWidth(2, 180)
        self.dependencies.setAccessibleName('Объявленные зависимости включённых модов')
        tabs.addTab(self.dependencies, 'Зависимости')
        trial_actions = QHBoxLayout()
        self.prepare_trial = QPushButton('Создать пробную копию…')
        self.prepare_trial.setToolTip('Подготовить копию без мода из выбранного результата. Изменение требует подтверждения.')
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
        scope = QLabel('Локальная проверка · без запуска игры')
        scope.setObjectName('muted')
        scope.setWordWrap(True)
        actions.addWidget(scope, 1)
        actions.addWidget(self.scan)
        self.close_button = QPushButton('Закрыть')
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.scan.setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'issues_splitter'):
            compact = self.width() < 820
            self.workspace_eyebrow.setVisible(not compact)
            self.workspace_layout.setSpacing(8 if compact else 12)
            self.workspace_title.setProperty('compact', compact)
            self.workspace_title.style().unpolish(self.workspace_title)
            self.workspace_title.style().polish(self.workspace_title)
            for card, value in zip(self.summary_cards, self.summary_values):
                card.layout().setContentsMargins(12, 6 if compact else 10, 12, 6 if compact else 10)
                value.setProperty('compact', compact)
                value.style().unpolish(value)
                value.style().polish(value)
            orientation = Qt.Orientation.Vertical if compact else Qt.Orientation.Horizontal
            if self.issues_splitter.orientation() != orientation:
                self.issues_splitter.setOrientation(orientation)
                self.issues_splitter.setSizes([130, 180] if compact else [360, 560])

    def start_scan(self):
        if self.worker is not None or self.review_dialog is not None:
            return
        self.report = None
        self.findings.clear()
        self.dependencies.clear()
        self.evidence.clear()
        self.detail_title.setText('Читаем сборку…')
        for value in self.summary_values:
            value.setText('—')
        self.progress.setRange(0, 0)
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
        matched = sum(c.status == 'MATCH' for c in report.version_checks)
        mismatched = sum(c.status == 'MISMATCH' for c in report.version_checks)
        unknown = sum(c.status == 'UNKNOWN' for c in report.version_checks)
        self.status.setText(f'Прочитано JAR: {len(report.mods)} · Замечаний: {count} · ' + ('Обход завершён.' if report.complete else 'Отчёт неполный.') + f' Условия версий: выполнено {matched}, не выполнено {mismatched}, не проверено {unknown}. Успешный запуск не подтверждён.')
        for label, value in zip(self.summary_values, (len(report.mods), count, unknown)):
            label.setText(str(value))
        levels = {'error': 'Ошибка', 'warning': 'Внимание', 'info': 'Сведения'}
        for finding in report.findings:
            item = QListWidgetItem(levels[finding.level] + '\n' + redact(finding.title))
            item.setSizeHint(QSize(0, 72))
            item.setForeground(QColor(TOKENS[{'error':'danger', 'warning':'warning', 'info':'text'}[finding.level]]))
            item.setToolTip(redact(finding.title))
            self.findings.addItem(item)
        owners = {}
        for mod in report.mods:
            for identifier in mod.ids:
                owners.setdefault(identifier, []).append(mod.filename)
        implicit = {'minecraft', 'java'} | {'fabric': {'fabricloader'}, 'forge': {'forge'}, 'neoforge': {'neoforge'}}.get(self.loader, set())
        for mod in report.mods:
            versions = ', '.join(identifier+'@'+(version or '?') for identifier, version in mod.versions)
            parent = QTreeWidgetItem([mod.filename, versions[:240] or ', '.join(mod.ids) or 'ID не распознан', ', '.join(mod.loaders)])
            self.dependencies.addTopLevelItem(parent)
            for identifier, expression in mod.requires:
                location = 'Компонент среды; версия не проверена' if identifier in implicit else ', '.join(owners.get(identifier, [])) or 'Не найдена / не разрешена'
                checks = [c for c in report.version_checks if c.filename==mod.filename and c.dependency==identifier and c.expression==expression]
                check = checks[0] if len(checks)==1 else None
                labels = {'MATCH':'Условие выполнено', 'MISMATCH':'Не соответствует', 'UNKNOWN':'Не проверено'}
                label = labels[check.status] if check else 'Не проверено'
                actual = check.actual if check and check.actual else 'версия не определена'
                child = QTreeWidgetItem(parent, [identifier, (expression+' / '+actual)[:240], label])
                child.setToolTip(1, location[:512])
                child.setToolTip(2, check.reason if check else 'Неоднозначное объявление.')
                child.setData(2, Qt.ItemDataRole.AccessibleDescriptionRole, check.reason if check else 'Неоднозначное объявление.')
            if mod.nested:
                QTreeWidgetItem(parent, ['Вложенные JAR', 'Кандидаты — см. замечания', 'Загрузка не подтверждена'])
        self.dependencies.setColumnWidth(0,240)
        if self.findings.count():
            self.findings.setCurrentRow(0)

    def show_finding(self, row):
        if self.report is None or not 0 <= row < len(self.report.findings):
            return
        finding = self.report.findings[row]
        self.detail_title.setText(redact(finding.title))
        self.detail_kind.setText({'error':'ОШИБКА', 'warning':'ТРЕБУЕТ ВНИМАНИЯ', 'info':'СВЕДЕНИЯ'}[finding.level] + '  /  ИСТОЧНИКИ')
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
        self.progress.setRange(0, 0)
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
        self.prepare_trial.hide()
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
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if self.report else 0)
        if self.report is None:
            self.detail_title.setText("Проверка не завершена — попробуйте ещё раз")
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
