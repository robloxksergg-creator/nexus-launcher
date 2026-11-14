"""Prototype settings layout over the existing settings controls and signals."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout,QGridLayout,QPushButton


class SettingsWorkspace(QFrame):
    def __init__(self, owner):
        super().__init__()
        self.setObjectName("settingsWorkspace")
        self.owner = owner
        root = QHBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        desk=QFrame();desk.setMaximumWidth(1240)
        bounded=QHBoxLayout(desk);bounded.setContentsMargins(0,0,0,0);bounded.setSpacing(20)
        root.addStretch(1);root.addWidget(desk,100);root.addStretch(1)
        self.desk=desk
        self.setStyleSheet('''
            QFrame#settingsWorkspace {background:#07111e;}
            QFrame#settingsMenu {background:#102135;border:1px solid #294158;border-radius:16px;}
            QFrame#settingsMain {background:#0e1c2d;border:1px solid #294158;border-radius:16px;}
            QFrame#settingsMenu QListWidget {background:transparent;border:0;outline:0;}
            QFrame#settingsMenu QListWidget::item {padding:12px 10px;color:#acc1d8;border-radius:8px;margin:2px 0;}
            QFrame#settingsMenu QListWidget::item:selected {background:#244b6b;color:#e7f5ff;}
            QFrame#settingsMenu QLabel#cardTitle {font-size:22px;color:#e1f0ff;}
            QFrame#settingsMain QLabel#settingsHeading {font-family:"Segoe UI";font-size:30px;font-weight:600;color:#e5f2ff;letter-spacing:0;}
            QFrame#settingsMain QLabel#settingLine {background:#142b42;border:1px solid #2d4c66;border-radius:10px;padding:16px 18px;min-height:48px;}
            QFrame#settingsMain QPushButton {padding:10px 16px;border:1px solid #3b5c7a;border-radius:9px;background:#203e59;color:#dceeff;}
            QFrame#settingsMain QPushButton:hover {background:#305674;}
            QFrame#settingsMain QPushButton#settingsQuickLink {text-align:left;background:#122b41;border:1px solid #31526d;min-height:74px;padding:14px;font-size:13px;}
            QFrame#settingsMain QPushButton#settingsQuickLink:hover {background:#214762;border-color:#71a9ce;}
            QFrame#settingsMain QCheckBox {background:#142b42;border:1px solid #2d4c66;border-radius:9px;padding:13px;spacing:12px;}
            QFrame#settingsMain QSpinBox {background:#10263c;border:1px solid #3c5c77;border-radius:8px;padding:10px;color:#dceeff;}
            QFrame#settingsWorkspace QScrollArea,QFrame#settingsWorkspace QStackedWidget {background:transparent;border:0;}
        ''')
        menu = QFrame()
        menu.setObjectName("settingsMenu")
        menu.setFixedWidth(220)
        menu_layout = QVBoxLayout(menu)
        menu_layout.setContentsMargins(20, 20, 20, 20)
        title = QLabel("Настройки")
        title.setObjectName("cardTitle")
        menu_layout.addWidget(title)
        caption=QLabel('Твой лаунчер, твои параметры');caption.setWordWrap(True);caption.setObjectName('muted');menu_layout.addWidget(caption)
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
        bounded.addWidget(menu)
        self.content = QFrame()
        self.content.setObjectName("settingsMain")
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        owner.panels.setParent(self.content)
        # Each form owns its scroll; the menu and workspace stay stationary.
        for index in range(owner.panels.count()):
            panel = owner.panels.widget(index)
            panel.layout().setContentsMargins(24, 24, 24, 24)
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
        bounded.addWidget(self.content, 1)
        overview=QFrame();grid=QGridLayout(overview);grid.setContentsMargins(0,14,0,0);grid.setSpacing(12)
        label=QLabel('Быстрый доступ к параметрам');label.setObjectName('cardTitle');grid.addWidget(label,0,0,1,2)
        self.quick_links={}
        for position,index in enumerate((1,2,3,4,5,7)):
            link=QPushButton();link.setObjectName('settingsQuickLink');link.clicked.connect(lambda _=False,target=index:owner.categories.setCurrentRow(target))
            grid.addWidget(link,position//2+1,position%2);self.quick_links[index]=link
        owner.general_values.layout().insertWidget(owner.general_values.layout().count()-1,overview)
        owner.categories.currentRowChanged.connect(lambda *_:self._refresh_overview())
        self._refresh_overview()
        self.search.textChanged.connect(self._filter)

    def _refresh_overview(self):
        config=self.owner.config
        summaries={1:f"Память: {int(config.get('memory',4096)) / 1024:g} ГБ · параметры запуска",2:'Среда выполнения и путь к Java',3:'Папки данных и использование диска',4:'Источники и проверка файлов',5:'Уменьшение движения: '+('включено' if config.get('reducedMotion') else 'выключено'),7:'Журналы игры и отчёты о сбоях'}
        for index,button in self.quick_links.items():
            button.setText(self.owner.categories.item(index).text()+'  →\n'+summaries[index])

    def showEvent(self,event):
        super().showEvent(event)
        if hasattr(self,'quick_links'):self._refresh_overview()

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
        menu.setFixedWidth(190 if self.width() < 1000 else 220)
