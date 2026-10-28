"""Prototype settings layout over the existing settings controls and signals."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout


class SettingsWorkspace(QFrame):
    def __init__(self, owner):
        super().__init__()
        self.setObjectName("settingsWorkspace")
        self.owner = owner
        root = QHBoxLayout(self)
        root.setContentsMargins(40, 32, 40, 32)
        root.setSpacing(24)
        menu = QFrame()
        menu.setObjectName("settingsMenu")
        menu.setFixedWidth(250)
        menu_layout = QVBoxLayout(menu)
        menu_layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Настройки")
        title.setObjectName("cardTitle")
        menu_layout.addWidget(title)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти настройку")
        self.search.setToolTip('Поиск по разделам и названиям настроек')
        self.search.setAccessibleName("Поиск настроек")
        self.search.setClearButtonEnabled(True)
        menu_layout.addWidget(self.search)
        owner.categories.setParent(menu)
        owner.categories.setMinimumWidth(0)
        owner.categories.setMaximumWidth(16777215)
        owner.categories.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        owner.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        menu_layout.addWidget(owner.categories, 1)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setObjectName("muted")
        menu_layout.addWidget(self.result)
        root.addWidget(menu)
        self.content = QFrame()
        self.content.setObjectName("settingsMain")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        owner.panels.setParent(self.content)
        # Each form owns its scroll; the menu and workspace stay stationary.
        for index in range(owner.panels.count()):
            panel = owner.panels.widget(index)
            panel.layout().setContentsMargins(32, 32, 32, 32)
            heading = panel.findChild(QLabel, 'settingsHeading')
            if heading:
                heading.setText(owner.categories.item(index).text())
            for label in panel.findChildren(QLabel):
                label.setWordWrap(True)
        self.scroller = QScrollArea()
        self.scroller.setWidgetResizable(True)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroller.setWidget(owner.panels)
        content_layout.addWidget(self.scroller)
        root.addWidget(self.content, 1)
        self.search.textChanged.connect(self._filter)

    def _filter(self, query):
        query = query.strip().casefold()
        visible = []
        for index in range(self.owner.categories.count()):
            item = self.owner.categories.item(index)
            panel = self.owner.panels.widget(index)
            captions = " ".join(label.text() for label in panel.findChildren(QLabel))
            match = not query or query in (item.text() + " " + captions).casefold()
            item.setHidden(not match)
            if match:
                visible.append(index)
        self.result.setText("Разделы не найдены. Измените запрос." if not visible else "")
        if visible and self.owner.categories.currentRow() not in visible:
            self.owner.categories.setCurrentRow(visible[0])

    def resizeEvent(self, event):
        super().resizeEvent(event)
        menu = self.findChild(QFrame, "settingsMenu")
        menu.setFixedWidth(200 if self.width() < 1000 else 250)
