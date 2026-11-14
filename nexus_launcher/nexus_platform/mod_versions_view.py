"""Native, inert compatible-version cards with an explicit install action."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QFrame


class ModVersionsView(QScrollArea):
    def __init__(self):
        super().__init__();self.setWidgetResizable(True)
        self.body=QWidget();self.box=QVBoxLayout(self.body);self.box.setContentsMargins(12,12,12,12);self.box.setSpacing(10);self.setWidget(self.body)
        self.rows=[];self.installed=set();self.busy=False
    def cancel_media(self):pass
    def setPlainText(self,text):
        self.rows=[];self._clear();label=QLabel(text);label.setWordWrap(True);self.box.addWidget(label);self.box.addStretch()
    def _clear(self):
        while self.box.count():
            item=self.box.takeAt(0)
            if item.widget():item.widget().deleteLater()
    def set_versions(self,versions,installed,callback):
        self.rows=list(versions[:500]);self.limit=50;self.installed=set(installed);self.callback=callback;self._render()
    def set_installed(self,installed):
        self.installed=set(installed)
        if self.rows:self._render()
    def set_busy(self,busy):
        self.busy=busy
        if self.rows:self._render()
    def _render(self):
        position=self.verticalScrollBar().value();self._clear()
        for version in self.rows[:self.limit]:
            card=QFrame();card.setObjectName('modRow');layout=QHBoxLayout(card);layout.setContentsMargins(18,14,18,14)
            copy=QVBoxLayout();title=QLabel(str(version.get('name') or version.get('version_number') or 'Версия мода'));title.setTextFormat(Qt.PlainText);title.setWordWrap(True)
            copy.addWidget(title)
            kind={'release':'Релиз','beta':'Бета','alpha':'Альфа'}.get(version.get('version_type'),'Версия')
            text=f"{kind} · {str(version.get('date_published',''))[:10]} · {', '.join(version.get('loaders',[]))} · Minecraft {', '.join(version.get('game_versions',[]))}"
            meta=QLabel(text);meta.setTextFormat(Qt.PlainText);meta.setWordWrap(True);meta.setObjectName('modMetadata');copy.addWidget(meta);layout.addLayout(copy,1)
            present=version.get('id') in self.installed
            action=QPushButton('Установлена' if present else 'Установить эту версию');action.setObjectName('primaryAction' if not present else '')
            action.setEnabled(bool(version.get('id')) and not present and not self.busy)
            action.clicked.connect(lambda _=False,key=version.get('id'):self.callback(key));layout.addWidget(action)
            self.box.addWidget(card)
        if not self.rows:self.box.addWidget(QLabel('Совместимых версий нет.'))
        if len(self.rows)>self.limit:
            more=QPushButton('Показать ещё версии');more.clicked.connect(self._more);self.box.addWidget(more)
        self.box.addStretch();self.verticalScrollBar().setValue(position)
    def _more(self):
        self.limit+=50;self._render()
