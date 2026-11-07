"""Read-only native catalogue. No remote source or download execution."""
import threading
from PySide6.QtCore import Signal, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QLabel,QPushButton,QScrollArea,QWidget


class CreatorCatalogueDialog(QDialog):
    result_ready = Signal(object)
    failed = Signal()

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client, self.cursor = client, None
        self.setWindowTitle('NEXUS · Серверы сообщества')
        self.resize(760,650)
        root=QVBoxLayout(self)
        self.status=QLabel('Серверы сообщества')
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        host=QWidget()
        self.rows=QVBoxLayout(host)
        self.rows.setAlignment(Qt.AlignTop)
        scroll.setWidget(host)
        root.addWidget(scroll)
        self.refresh=QPushButton('Обновить каталог')
        self.refresh.clicked.connect(lambda:self.load(False))
        self.more=QPushButton('Следующая страница')
        self.more.clicked.connect(lambda:self.load(True))
        self.more.hide()
        root.addWidget(self.refresh)
        root.addWidget(self.more)
        close=QPushButton('Закрыть')
        close.clicked.connect(self.close)
        root.addWidget(close)
        self.result_ready.connect(self.apply)
        self.failed.connect(self.failure)
        self.load(False)

    def load(self, more=False):
        self.refresh.setEnabled(False)
        self.more.setEnabled(False)
        self.status.setText('Загружаем выпущенные записи…')
        cursor=self.cursor if more else None
        while self.rows.count():self.rows.takeAt(0).widget().deleteLater()
        def worker():
            try:self.result_ready.emit(self.client.creator_catalogue(cursor))
            except Exception:self.failed.emit()
        threading.Thread(target=worker,daemon=True).start()

    def apply(self,data):
        self.refresh.setEnabled(True)
        self.more.setEnabled(True)
        self.cursor=data['next']
        self.more.setVisible(bool(self.cursor))
        self.status.setText('Выпущенные записи · пакеты требуют отдельной проверки.' if data['items'] else 'Выпущенных записей пока нет.')
        for row in data['items']:
            panel=QWidget()
            layout=QVBoxLayout(panel)
            access={'PUBLIC':'Бесплатно','PAID':'Платно · оплата не подключена','PRIVATE':'Приватно · по приглашению'}[row['access']]
            for text in (row['name'],row['summary'],f"{row['genre']} · {row['version']} · {row['loader']}",access):
                label=QLabel(text)
                label.setTextFormat(Qt.PlainText)
                label.setWordWrap(True)
                layout.addWidget(label)
            if row['website']:
                button=QPushButton('Открыть страницу на сайте')
                button.clicked.connect(lambda _=False,path=row['website']:QDesktopServices.openUrl(QUrl('https://nexusmc.flux-productions.com'+path)))
                layout.addWidget(button)
            download=QPushButton('Скачивание: проверенный пакет ещё не подключён')
            download.setEnabled(False)
            layout.addWidget(download)
            self.rows.addWidget(panel)

    def failure(self):
        self.refresh.setEnabled(True)
        self.more.hide()
        self.cursor=None
        self.status.setText('Каталог недоступен. Повторите обновление. Доступ к сборкам не изменён.')
