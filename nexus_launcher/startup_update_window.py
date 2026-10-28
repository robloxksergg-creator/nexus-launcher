"""NEXUS startup window. Explicit backend injection; not a production entrypoint.

Uses one background worker. No nested launcher event loop, network on the GUI
thread, automatic retry, cancellation during activation, or exception disclosure.
"""
from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QPushButton, QVBoxLayout

from nexus_launcher.themed_dialog import NexusDialog
from nexus_launcher.nexus_platform.presentation_style import stylesheet
from nexus_launcher.nexus_platform.theme_tokens import TOKENS
from nexus_launcher.startup_update_flow import Phase, StartupFlow


class _Attempt(QThread):
    changed = Signal(object)

    def __init__(self, flow, offline, parent):
        super().__init__(parent)
        self.flow, self.offline = flow, offline

    def run(self):
        self.flow.run(offline=self.offline)


class StartupUpdateWindow(NexusDialog):
    launcher_ready = Signal()

    def __init__(self, backend, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NEXUS — запуск")
        self.setMinimumSize(480, 400)
        self.resize(520, 440)
        self.setStyleSheet(stylesheet() + f"QDialog {{ background:{TOKENS['background']}; }}")
        self.worker = None
        self.flow = StartupFlow(backend, self._dispatch)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(16)
        brand = QLabel("NEXUS")
        brand.setStyleSheet(f"font-family:Bahnschrift; font-size:36px; font-weight:700; color:{TOKENS['accent']}")
        layout.addWidget(brand, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()
        self.title = QLabel()
        self.title.setWordWrap(True)
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title.setStyleSheet("font-size:22px; font-weight:600")
        layout.addWidget(self.title)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setMinimumHeight(64)
        layout.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.setAccessibleName("Ход обновления")
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        self.progress.setStyleSheet(f"QProgressBar {{ background:{TOKENS['surface']}; border:0; border-radius:3px; }}"
                                   f"QProgressBar::chunk {{ background:{TOKENS['accent']}; }}")
        layout.addWidget(self.progress)
        layout.addStretch()
        actions = QVBoxLayout()
        self.retry = QPushButton("Повторить")
        self.retry.setObjectName("primaryAction")
        self.offline = QPushButton("Запустить установленную")
        self.retry.clicked.connect(lambda: self.start())
        self.offline.clicked.connect(lambda: self.start(offline=True))
        actions.addWidget(self.retry)
        actions.addWidget(self.offline)
        layout.addLayout(actions)
        self.render(self.flow.view)

    def _dispatch(self, view):
        # Called by the background owner; queued Qt signal is the only UI path.
        self.worker.changed.emit(view)

    def start(self, *, offline=False):
        if self.worker is not None or self.flow.view.phase in {Phase.READY, Phase.BLOCKED}:
            return
        self.retry.setEnabled(False)
        self.offline.setEnabled(False)
        self.worker = _Attempt(self.flow, offline, self)
        self.worker.changed.connect(self.render)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.render(self.flow.view)
        if self.flow.view.phase == Phase.READY:
            self.launcher_ready.emit()
            self.accept()

    def render(self, view):
        self.title.setText(view.title)
        self.detail.setText(view.detail)
        self.retry.setVisible(view.retry)
        self.offline.setVisible(view.offline)
        self.retry.setEnabled(view.retry and self.worker is None)
        self.offline.setEnabled(view.offline and self.worker is None)
        busy = view.phase in {Phase.CHECKING, Phase.DOWNLOADING, Phase.VERIFYING, Phase.STARTING}
        if hasattr(self, 'title_bar'):
            self.title_bar.close_button.setEnabled(not busy and self.worker is None)
            self.title_bar.close_button.setToolTip("Дождитесь завершения операции" if busy else "Закрыть окно")
        self.progress.setVisible(busy)
        self.progress.setRange(0, 100 if view.percent is not None else 0)
        if view.percent is not None:
            self.progress.setValue(view.percent)
        self.title.setAccessibleName(view.title)

    def reject(self):
        if self.worker is None:
            super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            event.ignore()
        else:
            super().closeEvent(event)
