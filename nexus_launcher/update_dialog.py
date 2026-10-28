import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QPushButton, QVBoxLayout
from nexus_launcher.self_update import SelfUpdater


class Events(QObject):
    progress = Signal(int, int)
    ready = Signal(str)
    failed = Signal(str)


from nexus_launcher.themed_dialog import NexusDialog


class UpdateDialog(NexusDialog):
    def __init__(self, parent, release):
        super().__init__(parent)
        self.release = release
        self.updater = SelfUpdater()
        self.busy = False
        self.setWindowTitle("Обновление NEXUS")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        self.status = QLabel(f"Доступна версия {release.version}\n{release.notes}")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar()
        layout.addWidget(self.progress)
        self.download = QPushButton("Скачать и установить")
        self.download.clicked.connect(self.start)
        layout.addWidget(self.download)
        self.skip = QPushButton("Пропустить")
        self.skip.clicked.connect(self.reject)
        layout.addWidget(self.skip)
        self.events = Events(self)
        self.events.progress.connect(lambda done, total: self.progress.setValue(int(done * 100 / max(1, total))))
        self.events.failed.connect(self.failed)
        self.events.ready.connect(self.ready)

    def reject(self):
        if not self.busy:
            super().reject()

    def start(self):
        if self.busy:
            return
        self.busy = True
        self.download.setEnabled(False)
        self.skip.setEnabled(False)
        self.status.setText("Загрузка обновления…")

        def worker():
            try:
                path = self.updater.download(self.release, self.events.progress.emit)
                self.events.ready.emit(str(path))
            except Exception as error:
                self.events.failed.emit(str(error))

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            self.failed(str(error))

    def failed(self, message):
        self.busy = False
        self.status.setText(f"Ошибка обновления: {message}")
        self.download.setText("Повторить")
        self.download.setEnabled(True)
        self.skip.setEnabled(True)

    def ready(self, path):
        self.status.setText("Проверено. Установка и перезапуск…")
        try:
            self.updater.install_after_exit(Path(path))
        except Exception as error:
            self.failed(str(error))
            return
        self.busy = False
        self.accept()
        QApplication.instance().quit()
