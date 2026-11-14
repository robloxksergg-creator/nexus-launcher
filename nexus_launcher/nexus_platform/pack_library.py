"""Presentation-only library adapter; original instance operations are retained."""
import threading

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QLayout, QStackedWidget, QTabWidget, QVBoxLayout, QWidget, QFrame, QSizePolicy, QBoxLayout,
    QMessageBox, QComboBox, QCheckBox, QMenu,
)

from nexus_launcher.instance_ui import InstancePage
from .mod_catalog import ModCatalog
from .artwork import ArtworkSurface
from .workspace_visuals import BrandSurface, panel, reveal, workspace_style
from .workspace_visuals import monogram, workspace_menu
from .theme_tokens import WORKSPACE
from .library_components import ArtworkCard, ArtworkGrid, InstalledModDelegate
from .content_state import ContentState
from PySide6.QtGui import QIcon


class PackLibraryPage(InstancePage):
    def _build(self):
        super()._build()
        from .installed_mod_media import InstalledModMedia
        self.installed_media=InstalledModMedia(self)
        self.installed_media.updated.connect(self._installed_art_ready)
        # Keep original data selection/model, retire its duplicate visible library.
        self.setStyleSheet(workspace_style())
        self.workspace.layout().itemAt(0).widget().hide()
        self.mods_search.setClearButtonEnabled(True)
        self.mods.setItemDelegate(InstalledModDelegate(self.mods))
        self.mods.itemActivated.connect(self._open_installed_item)
        self.instance_title.setObjectName("workspaceTitle")
        self.instance_title.setWordWrap(True)
        self.instance_stats.setWordWrap(True)
        self.instance_stats.setObjectName("muted")
        self.launch_button.setObjectName("primaryAction")
        self.launch_button.setText("Играть")
        self.launch_button.setFixedSize(144, 42)
        self.context_button.setFixedSize(42, 42)
        self.context_button.setText('...')
        self.context_button.setObjectName('buildMoreAction')
        root = self.layout()
        detail = QWidget()
        detail_outer = QVBoxLayout(detail)
        detail_outer.setContentsMargins(0, 0, 0, 0)
        self.detail_scroll = QScrollArea()
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        detail_content = QWidget()
        detail_layout = QVBoxLayout(detail_content)
        detail_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.detail_scroll.setWidget(detail_content)
        detail_outer.addWidget(self.detail_scroll)
        self.context_button.setAccessibleName('Действия со сборкой')
        self.context_button.setToolTip('Управление сборкой и резервными копиями')
        back = QPushButton("Назад к сборкам")
        back.clicked.connect(self.show_library)
        detail_layout.addWidget(back, 0, Qt.AlignLeft)
        header = BrandSurface()
        self.build_hero = header
        header.setMinimumHeight(200)
        header.setObjectName("packHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 40, 32, 24)
        titles = QVBoxLayout()
        for control in (self.instance_title, self.instance_meta):
            control.setParent(header)
            titles.addWidget(control)
        self.last_played = QLabel()
        self.last_played.setObjectName("muted")
        titles.addWidget(self.last_played)
        self.diagnostics_card.hide()
        header_layout.addLayout(titles, 1)
        for control in (self.launch_button, self.context_button):
            control.setParent(header)
            header_layout.addWidget(control)
        detail_layout.addWidget(header)
        while root.count():
            item = root.takeAt(0)
            if item.widget() is self.page_state:
                detail_layout.addWidget(self.page_state, 1)
            elif item.widget():
                item.widget().hide()
                item.widget().setParent(detail)
        self.library_stack = QStackedWidget()
        self.library = QWidget()
        layout = QVBoxLayout(self.library)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        heading = QLabel("Мои сборки")
        heading.setObjectName("workspaceTitle")
        layout.addWidget(heading)
        copy = QLabel("Отдельная версия Minecraft для каждой твоей истории.")
        copy.setObjectName("muted")
        layout.addWidget(copy)
        actions = QHBoxLayout()
        for label, callback in (("Создать сборку", self._create), ("Импортировать ZIP", self._import_zip),
                                ("Импортировать папку", self._import_folder)):
            button = QPushButton(label)
            button.setMinimumHeight(40)
            if label == "Создать сборку":
                button.setObjectName("primaryAction")
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.pack_search = QLineEdit()
        self.pack_search.setPlaceholderText("Найти свою сборку")
        self.pack_search.setAccessibleName("Поиск своих сборок")
        self.pack_search.setClearButtonEnabled(True)
        self.pack_search.textChanged.connect(self._filter_cards)
        layout.addWidget(self.pack_search)
        self.pack_cards = ArtworkGrid()
        self.pack_cards.setAccessibleName("Библиотека сборок; нажмите для открытия")
        self.pack_cards.itemClicked.connect(self._open_card)
        self.pack_cards.itemActivated.connect(self._open_card)
        layout.addWidget(self.pack_cards, 1)
        self.library_empty = BrandSurface()
        self.library_empty.set_artwork("", "first-world")
        self.library_empty.setMinimumHeight(180)
        self.library_empty.setMaximumHeight(210)
        empty_box = QVBoxLayout(self.library_empty)
        empty_box.setContentsMargins(24, 24, 24, 24)
        empty_box.setSpacing(12)
        self.empty_heading = QLabel("Здесь будут твои сборки")
        self.empty_heading.setObjectName("cardTitle")
        empty_box.addWidget(self.empty_heading)
        self.empty_copy = QLabel("Нажми «Создать сборку» выше или импортируй готовую. Установленные сборки появятся в этом списке.")
        self.empty_copy.setObjectName("muted")
        self.empty_copy.setWordWrap(True)
        empty_box.addWidget(self.empty_copy)
        empty_create = QPushButton("Создать сборку")
        empty_create.setObjectName("primaryAction")
        empty_create.clicked.connect(self._create)
        empty_create.show()
        empty_box.addWidget(empty_create, 0, Qt.AlignLeft)
        layout.addWidget(self.library_empty)
        self.library_status = QLabel()
        self.library_status.setObjectName("muted")
        layout.addWidget(self.library_status)
        layout.addStretch(1)
        self.library_stack.addWidget(self.library)
        self.library_stack.addWidget(detail)
        self.mod_catalog = ModCatalog(self)
        self.library_stack.addWidget(self.mod_catalog)
        self.mod_catalog.back_requested.connect(self._close_catalog)
        self.mod_catalog.install_requested.connect(self._catalog_install)
        self.mod_catalog.batch_install_requested.connect(self._catalog_install_batch)
        self.mod_catalog.version_install_requested.connect(self._catalog_install_version)
        original_catalog = self.detail.widget(2)
        self.detail.removeTab(2)
        original_catalog.hide()
        original_catalog.deleteLater()
        add_content = QPushButton("Добавить контент")
        add_content.setMinimumHeight(42)
        add_content.clicked.connect(self.open_mod_catalog)
        self.detail.widget(1).layout().addWidget(add_content)
        add_content.setObjectName("primaryAction")
        add_content.setText("Найти моды на Modrinth")
        self.find_mods_action = add_content
        mod_panel = self.detail.widget(1)
        updates = QPushButton("Проверить обновления модов")
        updates.clicked.connect(self._update_mods)
        mod_panel.layout().removeWidget(self.mods_search)
        search_tools = QHBoxLayout()
        self.find_build_action=QPushButton('Найти сборку')
        self.find_build_action.clicked.connect(self._find_build)
        search_tools.addWidget(self.find_build_action)
        search_tools.addWidget(self.mods_search, 1)
        self.installed_filter = QComboBox()
        self.installed_filter.addItems(['Все моды', 'Включённые', 'Отключённые', 'Modrinth', 'Локальные JAR'])
        self.installed_filter.setAccessibleName('Фильтр установленных модов')
        self.installed_filter.currentIndexChanged.connect(self._filter_installed_mods)
        self.mods_search.textChanged.connect(self._filter_installed_mods)
        search_tools.addWidget(self.installed_filter)
        mod_panel.layout().removeWidget(add_content)
        add_content.setText('Найти моды')
        search_tools.addWidget(add_content)
        action_tools = QHBoxLayout()
        action_tools.addStretch(1)
        action_tools.addWidget(updates)
        # Keep file-level actions in the compact header, individual actions in rows.
        for button in mod_panel.findChildren(QPushButton):
            if button.text() in {'Включить / отключить', 'Удалить мод'}:
                button.hide()
            elif button.text() in {'Добавить JAR', 'Открыть папку'}:
                action_tools.addWidget(button)
        mod_panel.layout().insertLayout(0, search_tools)
        mod_panel.layout().insertLayout(1, action_tools)
        self.mods_empty = ContentState("Моды меняют правила игры.",
                                       "Найди дополнения для этой версии Minecraft или добавь свой JAR.",
                                       "Найти моды", lambda: self._create() if self.current and self.current.loader == "vanilla" else self.open_mod_catalog(), "mods")
        mod_panel.layout().insertWidget(1, self.mods_empty, 1)
        self._migrate_content_tabs()
        self._refine_workspace()
        self.library_stack.setMaximumWidth(WORKSPACE['width'])
        self.library_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.setContentsMargins(20, 20, 20, 20)
        bounded = QHBoxLayout()
        bounded.addStretch(1)
        bounded.addWidget(self.library_stack, 100)
        bounded.addStretch(1)
        root.addLayout(bounded)
        self.detail_surface = detail

    def _migrate_content_tabs(self):
        # Core operations stay reachable, but are not personal-pack content tabs.
        self.advanced_tabs = QTabWidget()
        secondary = [(self.detail.widget(index), self.detail.tabText(index))
                     for index in range(self.detail.count()) if index != 1]
        for widget, caption in secondary:
            self.detail.removeTab(self.detail.indexOf(widget))
            self.advanced_tabs.addTab(widget, "Сведения" if caption == "Обзор" else caption)
        self.content_lists = {}
        for caption, relative in (("Ресурс-паки", "resourcepacks"), ("Миры", "saves"),
                                  ("Дата-паки", "datapacks"), ("Шейдеры", "shaderpacks")):
            panel = QWidget()
            layout = QVBoxLayout(panel)
            descriptions = {
                "resourcepacks": ("Новый взгляд на знакомый мир.", "Добавь ресурс-пак в папку resourcepacks этой сборки."),
                "saves": ("Твоя история ещё впереди.", "Сохрани мир из Minecraft или перенеси его в папку saves."),
                "datapacks": ("Свои правила для каждого мира.", "Дата-паки устанавливаются в папку datapacks конкретного сохранения."),
                "shaderpacks": ("Свет меняет всё.", "Добавь шейдеры в папку shaderpacks. Для работы нужен совместимый мод."),
            }
            empty = ContentState(*descriptions[relative], "Открыть папку",
                                 lambda _=False, path="saves" if relative == "datapacks" else relative: self._open_relative(path), relative)
            empty.default_copy = descriptions[relative]
            listing = QListWidget()
            listing.setAccessibleName(caption + " текущей сборки")
            if relative == "saves":
                listing.setViewMode(QListWidget.IconMode)
                listing.setResizeMode(QListWidget.Adjust)
                listing.setMovement(QListWidget.Static)
                listing.setSpacing(12)
                listing.setGridSize(QSize(302, 226))
                listing.itemActivated.connect(lambda item: self._open_relative("saves/" + item.text()))
            layout.addWidget(empty)
            layout.addWidget(listing, 1)
            folder = QPushButton("Открыть папку миров" if relative == "datapacks" else "Открыть папку")
            folder.clicked.connect(lambda _=False, path="saves" if relative == "datapacks" else relative: self._open_relative(path))
            layout.addWidget(folder, 0, Qt.AlignLeft)
            self.detail.addTab(panel, caption)
            self.content_lists[relative] = (listing, empty)
        body = self.workspace.layout()
        body.removeWidget(self.detail)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.detail, 1)
        # Reuse original panels once, in the same detail navigation. No duplicate
        # settings/files/backups UI and no secondary hidden maintenance rail.
        retained = []
        while self.advanced_tabs.count():
            panel = self.advanced_tabs.widget(0)
            caption = self.advanced_tabs.tabText(0)
            self.advanced_tabs.removeTab(0)
            retained.append((panel, caption))
        for panel, caption in retained:
            if caption == "Сведения":
                self.detail.insertTab(0, panel, "Обзор")
            elif caption == "Настройки":
                self.detail.addTab(panel, caption)
            else:
                self.advanced_tabs.addTab(panel, caption)
        self.detail.addTab(self.advanced_tabs, "Файлы и копии")
        self.detail.setUsesScrollButtons(True)
        self.detail.setMinimumHeight(440)
        self.detail.setCurrentIndex(0)
        self.instance_stats.hide()
        overview = self.overview.layout()
        introduction = QLabel("Твоя версия Minecraft. Все дополнения, сохранения и параметры живут внутри этой сборки.")
        introduction.setWordWrap(True)
        introduction.setObjectName("muted")
        overview.insertWidget(0, introduction)
        facts = QGridLayout()
        facts.setHorizontalSpacing(32)
        facts.setVerticalSpacing(16)
        self.overview_facts = {}
        for index, caption in enumerate(("Моды", "Ресурсы", "Шейдеры", "Память", "Миры", "Последний запуск")):
            cell = QFrame()
            cell.setObjectName("workspacePanel")
            box = QVBoxLayout(cell)
            box.setContentsMargins(18, 14, 18, 14)
            label = QLabel(caption)
            label.setObjectName("muted")
            value = QLabel()
            value.setObjectName("workspaceMetric")
            value.setWordWrap(True)
            box.addWidget(label)
            box.addWidget(value)
            facts.addWidget(cell, index // 3, index % 3)
            self.overview_facts[caption] = value
        overview.insertLayout(1, facts)
        body.addWidget(content, 1)

    def _refine_workspace(self):
        """Reparent original controls, preserving service handlers and validation."""
        self.detail.setObjectName('packWorkspaceTabs')
        self.detail.currentChanged.connect(lambda _index: reveal(self.detail.currentWidget()))
        self.library_stack.currentChanged.connect(lambda _index: reveal(self.library_stack.currentWidget()))
        for i in range(self.detail.count()):
            if self.detail.tabText(i) == 'Настройки':
                settings = self.detail.widget(i)
                form = settings.layout()
                buttons = settings.findChildren(QPushButton)
                while form.count():
                    item = form.takeAt(0)
                    if item.widget() and isinstance(item.widget(), QLabel):
                        item.widget().deleteLater()
                # Delete only the now-empty layout; widgets and connections survive.
                from shiboken6 import delete
                delete(form)
                layout = QVBoxLayout(settings)
                layout.setContentsMargins(22, 22, 22, 22)
                layout.setSpacing(18)
                self.settings_columns = QBoxLayout(QBoxLayout.LeftToRight)
                self.settings_columns.setSpacing(18)
                runtime, box = panel('Производительность', 'Эти параметры применяются только к выбранной сборке.')
                for caption, field, hint in (
                    ('Память, МБ', self.memory, 'Не выделяй игре всю доступную оперативную память.'),
                    ('Путь к Java', self.java, 'Оставь пустым для автоматического выбора.'),
                    ('Аргументы JVM', self.jvm, 'Дополнительные параметры запуска Java.'),
                ):
                    label = QLabel(caption)
                    label.setBuddy(field)
                    box.addWidget(label)
                    field.setMaximumWidth(WORKSPACE['fieldWidth'])
                    box.addWidget(field)
                    help_text = QLabel(hint)
                    help_text.setObjectName('muted')
                    help_text.setWordWrap(True)
                    box.addWidget(help_text)
                self.settings_columns.addWidget(runtime, 3)
                storage, box = panel('Хранилище сборки', 'Изменение папки выполняется через существующую проверку переноса.')
                box.addWidget(self.install_path)
                tools = QHBoxLayout()
                for button in buttons:
                    if button.text() != 'Сохранить параметры':
                        tools.addWidget(button)
                tools.addStretch()
                box.addLayout(tools)
                box.addStretch()
                self.settings_columns.addWidget(storage, 2)
                layout.addLayout(self.settings_columns)
                for button in buttons:
                    if button.text() == 'Сохранить параметры':
                        button.setObjectName('primaryAction')
                        layout.addWidget(button, 0, Qt.AlignLeft)
                layout.addStretch()
        for i in range(self.advanced_tabs.count()):
            tab = self.advanced_tabs.widget(i)
            caption = self.advanced_tabs.tabText(i)
            if caption == 'Файлы':
                grid = tab.layout()
                buttons = tab.findChildren(QPushButton)
                while grid.count():
                    grid.takeAt(0)
                descriptions = {
                    'Ресурс-паки': 'Текстуры, звуки и оформление', 'Шейдеры': 'Свет и визуальные эффекты',
                    'Скриншоты': 'Сохранённые кадры из игры', 'Конфигурация': 'Настройки модов и загрузчика',
                    'Логи': 'Журналы запуска и ошибок', 'Миры': 'Локальные сохранения',
                }
                for index, button in enumerate(buttons):
                    card, box = panel(button.text(), descriptions.get(button.text(), ''))
                    button.setAccessibleName('Открыть папку: ' + button.text())
                    button.setText('Открыть папку ↗')
                    box.addWidget(button, 0, Qt.AlignLeft)
                    grid.addWidget(card, index//2, index%2)
                grid.setRowStretch(3, 1)
                grid.setSpacing(14)
            elif caption == 'Резервные копии':
                layout = tab.layout()
                title = QLabel('Точка возврата для твоей сборки')
                title.setObjectName('workspaceSection')
                layout.insertWidget(0, title)
                description = QLabel('Создай копию перед экспериментом. Восстановление создаёт отдельную сборку.')
                description.setWordWrap(True)
                description.setObjectName('muted')
                layout.insertWidget(1, description)
                self.backups_list.setMinimumHeight(150)
                self.backup_empty = ContentState('Пока нет резервных копий',
                    'Сохрани состояние сборки перед установкой новых модов или экспериментами.',
                    'Создать первую копию', self._backup, 'backups')
                layout.insertWidget(2, self.backup_empty)
                for button in tab.findChildren(QPushButton):
                    button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
                    if button.text() == 'Создать':button.setObjectName('primaryAction')
                    if button.text() == 'Удалить':button.setStyleSheet('color:#f4a4ab;')
        self.overview.layout().setSpacing(18)
        quick, box = panel('Продолжить работу', 'Моды, сохранения и параметры — в одном рабочем пространстве.')
        actions = QHBoxLayout()
        for label, target in (('Управлять модами', 'Моды'), ('Настроить запуск', 'Настройки'), ('Файлы и копии', 'Файлы и копии')):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, name=target: self._select_tab(name))
            actions.addWidget(button)
        actions.addStretch()
        box.addLayout(actions)
        self.overview.layout().insertWidget(2, quick)

    def _select_tab(self, caption):
        for i in range(self.detail.count()):
            if self.detail.tabText(i) == caption:
                self.detail.setCurrentIndex(i)
                return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'settings_columns'):
            self.settings_columns.setDirection(QBoxLayout.TopToBottom if self.width() < 1080 else QBoxLayout.LeftToRight)

    def _select(self, row):
        super()._select(row)
        if not self.current or not hasattr(self, "content_lists"):
            return
        root = self.service.path_for(self.current.id)
        self.install_path.setCursorPosition(0)
        self.install_path.setToolTip(self.install_path.text())
        self.backup_empty.setVisible(not self.backups_list.count())
        self.backups_list.setVisible(bool(self.backups_list.count()))
        self.build_hero.set_artwork(self.current.banner, self.current.id)
        played = self.current.last_launch[:10] if self.current.last_launch else "Ещё не запускалась"
        self.last_played.setText(f"{len(self.current.installed_mods)} модов · {self.current.memory_mb / 1024:g} ГБ памяти · Последний запуск: {played}")
        self.mods_empty.setVisible(not self.mods.count())
        self.find_mods_action.setVisible(True)
        self.mods.setVisible(bool(self.mods.count()))
        if self.current.loader == "vanilla":
            self.mods_empty.description.setText("Для модов нужен Fabric, Forge или NeoForge. Создай отдельную сборку с загрузчиком.")
            self.mods_empty.action.setText("Создать сборку с загрузчиком")
        else:
            self.mods_empty.description.setText("Найди дополнения для этой версии Minecraft или добавь свой JAR.")
            self.mods_empty.action.setText("Найти моды")
        # Keep item IDs/selection (used by core toggle/delete handlers) while
        # enriching read-only rows with truthful state and source information.
        for index, mod in enumerate(self.current.installed_mods):
            item = self.mods.item(index)
            source = "Modrinth" if mod.project_id and not mod.project_id.startswith('local:') else "Локальный JAR"
            item.setText(f"{mod.name}\n{'Включён' if mod.enabled else 'Отключён'} · {source}")
            item.setToolTip(f"{mod.filename}\nИдентификатор версии: {mod.version_id or 'не указан'}")
            # The row widget owns presentation; do not paint the retired delegate
            # underneath it or reserve a second decoration/icon column.
            item.setData(Qt.UserRole + 2, None)
            item.setIcon(QIcon())
            item.setSizeHint(QSize(200, 88))
            row_widget = QFrame()
            row_widget.setObjectName('installedModRow')
            row_box = QHBoxLayout(row_widget)
            row_box.setContentsMargins(14, 10, 14, 10)
            icon = QLabel();icon.setPixmap(monogram(mod.name, 40));icon.setFixedSize(40,40)
            row_box.addWidget(icon)
            copy = QVBoxLayout();copy.setSpacing(4)
            name = QLabel(mod.name);name.setObjectName('installedModName')
            name.setTextFormat(Qt.PlainText);name.setWordWrap(True)
            filename = QLabel(mod.filename);filename.setObjectName('muted')
            filename.setTextFormat(Qt.PlainText);filename.setToolTip(mod.filename)
            filename.setMinimumWidth(0)
            copy.addWidget(name);copy.addWidget(filename)
            row_box.addLayout(copy,1)
            origin = QLabel(source);origin.setObjectName('muted');origin.setFixedWidth(110);row_box.addWidget(origin)
            toggle = QCheckBox('Вкл.' if mod.enabled else 'Выкл.')
            toggle.setFixedWidth(88)
            toggle.setChecked(mod.enabled)
            toggle.setAccessibleName('Включить мод ' + mod.name)
            toggle.toggled.connect(lambda checked, filename=mod.filename, identifier=self.current.id:self._mod_row_action(identifier,filename,'toggle'))
            row_box.addWidget(toggle)
            actions = QPushButton('...');actions.setFixedWidth(36)
            actions.setStyleSheet('QPushButton{padding:0;font-size:20px;} QPushButton::menu-indicator{image:none;width:0;}')
            actions.setAccessibleName('Действия с модом ' + mod.name)
            menu = workspace_menu(actions)
            if mod.project_id and not mod.project_id.startswith('local:'):
                menu.addAction('Сменить версию…',lambda identifier=self.current.id,project=mod.project_id,title=mod.name:self._open_installed_mod(identifier,project,title,versions=True))
            menu.addAction('Удалить мод',lambda filename=mod.filename, identifier=self.current.id:self._mod_row_action(identifier,filename,'delete'))
            menu.addAction('Открыть папку', self._open_mods)
            actions.setMenu(menu);row_box.addWidget(actions)
            self.mods.setItemWidget(item,row_widget)
            row_widget.art_label=icon;row_widget.name_label=name
            if mod.project_id and not mod.project_id.startswith('local:'):
                row_widget.setCursor(Qt.PointingHandCursor)
                row_widget.mouseReleaseEvent=lambda event,identifier=self.current.id,project=mod.project_id,title=mod.name:self._open_installed_mod(identifier,project,title) if event.button()==Qt.LeftButton else None
                cached=self.installed_media.cache.get(mod.project_id)
                if cached:self._installed_art_ready(mod.project_id,cached)
                else:self.installed_media.request(mod.project_id)
        self.mods.setIconSize(QSize(48, 48))
        self._filter_installed_mods()
        for relative, (listing, empty) in self.content_lists.items():
            empty.title.setText(empty.default_copy[0])
            empty.description.setText(empty.default_copy[1])
            listing.clear()
            folder = root / relative
            try:
                if relative == "datapacks":
                    items = sorted((root / "saves").glob("*/datapacks/*"), key=lambda path: str(path).casefold())
                    listing.addItems([item.parent.parent.name + "/" + item.name for item in items])
                else:
                    items = sorted(folder.iterdir(), key=lambda path: path.name.casefold()) if folder.is_dir() else []
                    if relative == "saves":
                        items = [item for item in items if item.is_dir()][:512]
                    listing.addItems([item.name for item in items])
                    if relative == "saves":
                        for index, world in enumerate(items):
                            item = listing.item(index)
                            item.setSizeHint(QSize(280, 202))
                            cover = ArtworkSurface()
                            cover.set_artwork(world / "icon.png", world.name)
                            cover.setAttribute(Qt.WA_TransparentForMouseEvents)
                            box = QVBoxLayout(cover)
                            box.setContentsMargins(20, 20, 20, 20)
                            box.addStretch()
                            title = QLabel(world.name)
                            title.setTextFormat(Qt.PlainText)
                            title.setWordWrap(True)
                            title.setObjectName("cardTitle")
                            box.addWidget(title)
                            subtitle = QLabel("Локальное сохранение · открыть папку ↗")
                            subtitle.setObjectName("muted")
                            subtitle.setWordWrap(True)
                            box.addWidget(subtitle)
                            listing.setItemWidget(item, cover)
            except OSError:
                empty.title.setText("Не удалось прочитать папку.")
                empty.description.setText("Проверь доступ к файлам или открой папку вручную.")
                items = []
            empty.setVisible(not items)
            listing.setVisible(bool(items))
        values = {"Моды": str(len(self.current.installed_mods)), "Память": f"{self.current.memory_mb / 1024:g} ГБ",
                  "Последний запуск": played, "Ресурсы": str(self.content_lists["resourcepacks"][0].count()),
                  "Шейдеры": str(self.content_lists["shaderpacks"][0].count()),
                  "Миры": str(self.content_lists["saves"][0].count())}
        for caption, value in values.items():
            self.overview_facts[caption].setText(value)

    def refresh(self, select_id=""):
        super().refresh(select_id)
        self.pack_cards.clear()
        for instance in self.service.list():
            card = QListWidgetItem(f"{instance.name}\n{instance.minecraft_version} · {instance.loader.title()}")
            card.setData(Qt.UserRole, instance.id)
            card.setToolTip(instance.name)
            card.setSizeHint(QSize(320, 316))
            self.pack_cards.addItem(card)
            try:
                saves = self.service.path_for(instance.id) / 'saves'
                world_count = sum(path.is_dir() for path in saves.iterdir()) if saves.is_dir() else 0
            except OSError:
                world_count = None
            widget = ArtworkCard(instance, worlds=world_count)
            widget.clicked.connect(lambda _=False, item=card: self._open_card(item))
            widget.play_requested.connect(lambda item=card: self._play_card(item))
            self.pack_cards.setItemWidget(card, widget)
        self._filter_cards(self.pack_search.text())
        if select_id and self.current and self.current.id == select_id:
            self.library_stack.setCurrentWidget(self.detail_surface)
        else:
            self.show_library()

    def _filter_cards(self, query):
        visible = 0
        for index in range(self.pack_cards.count()):
            card = self.pack_cards.item(index)
            card.setHidden(query.casefold() not in card.text().casefold())
            visible += not card.isHidden()
        self.library_status.setText(
            f"Сборок: {visible}" if visible else
            ("Ничего не найдено. Измените поиск." if query else "Пока нет сборок. Создайте новую или импортируйте свою.")
        )
        self.pack_cards.setVisible(bool(visible))
        self.library_status.setObjectName("muted")
        self.library_status.setVisible(bool(visible))
        self.library.layout().setStretch(self.library.layout().count() - 1, 0 if visible else 1)
        self.library_status.setWordWrap(True)
        self.library_empty.setVisible(not visible)
        self.empty_heading.setText("Ничего не найдено." if query else "Здесь будут твои сборки")
        self.empty_copy.setText("Измени запрос или очисти поиск, чтобы увидеть все сборки." if query else
                               "Нажми «Создать сборку» выше или импортируй готовую. Установленные сборки появятся в этом списке.")

    def _build_context_menu(self):
        menu = workspace_menu(self)
        menu.addSection('Сборка')
        menu.addAction('Что мешает запуску?', self._open_diagnostics)
        menu.addAction('Открыть папку сборки', self._open_instance)
        menu.addSeparator()
        menu.addAction('Переименовать', self._rename)
        menu.addAction('Дублировать', self._duplicate)
        menu.addAction('Экспортировать ZIP', self._export_zip)
        menu.addAction('Изменить Minecraft / загрузчик…',self._change_runtime_version)
        backups = menu.addMenu('Резервные копии')
        backups.addAction('Создать резервную копию', self._backup)
        backups.addAction('Восстановить как новую сборку…', self._restore_backup)
        backups.addAction('Открыть папку копий', lambda:self._open_relative('.nexus/backups'))
        backups.addAction('Удалить резервную копию…', self._delete_backup)
        menu.addSeparator()
        menu.addAction('Убрать из библиотеки · сохранить файлы', self._forget)
        menu.addAction('Удалить файлы сборки…', self._delete)
        return menu

    def _change_runtime_version(self):
        if not self.current or self.mod_catalog.install_busy:
            self._task_failed('Дождитесь завершения установки модов.');return
        from .runtime_version_dialog import RuntimeVersionDialog
        from PySide6.QtWidgets import QDialog
        from nexus_launcher.diagnostic_trial import launcher_idle
        dialog=RuntimeVersionDialog(self.current,self)
        if dialog.exec()!=QDialog.Accepted:return
        owner=self.launch_owner if self.launch_owner is not None else self.window()
        try:
            with launcher_idle(owner):
                self.service.change_runtime(self.current.id,dialog.game.text().strip(),dialog.loader.currentText(),dialog.version.text().strip())
            self.mod_catalog.leave()
            self._task_done('Версия сборки изменена. Проверьте совместимость модов перед запуском.')
        except Exception as error:self._task_failed(str(error))

    def _installed_art_ready(self,project,data):
        if not self.current:return
        from .mod_media import decode_image
        from PySide6.QtGui import QPixmap
        records={mod.filename:mod for mod in self.current.installed_mods}
        image=decode_image(data.get('icon',b''),width=48,dimension=2048)
        for i in range(self.mods.count()):
            item=self.mods.item(i);mod=records.get(item.data(Qt.UserRole));row=self.mods.itemWidget(item)
            if mod and mod.project_id==project and hasattr(row,'art_label'):
                if not image.isNull():row.art_label.setPixmap(QPixmap.fromImage(image).scaled(40,40,Qt.KeepAspectRatio,Qt.SmoothTransformation))
                if data.get('title'):row.name_label.setText(data['title'])

    def _open_installed_item(self,item):
        if not self.current:return
        mod=next((m for m in self.current.installed_mods if m.filename==item.data(Qt.UserRole)),None)
        if mod and mod.project_id and not mod.project_id.startswith('local:'):
            self._open_installed_mod(self.current.id,mod.project_id,mod.name)

    def _open_installed_mod(self,instance_id,project_id,title,*,versions=False):
        if not self.current or self.current.id!=instance_id:return
        self.library_stack.setCurrentWidget(self.mod_catalog)
        self.mod_catalog.open_installed(self.service.load(instance_id),project_id,title)
        if versions:self.mod_catalog.project_tabs.setCurrentIndex(3)

    def _open_context_menu(self):
        if not self.current:
            return
        previous = getattr(self,'_context_menu',None)
        if previous:
            previous.close();previous.deleteLater()
        self._context_menu = self._build_context_menu()
        position=self.context_button.mapToGlobal(self.context_button.rect().bottomRight())
        position.setX(position.x()-self._context_menu.sizeHint().width())
        self._context_menu.popup(position)

    def _mod_row_action(self, instance_id, filename, action):
        if not self.current or self.current.id != instance_id:
            return
        for index in range(self.mods.count()):
            item = self.mods.item(index)
            if item.data(Qt.UserRole) == filename:
                self.mods.clearSelection()
                self.mods.setCurrentItem(item)
                item.setSelected(True)
                (self._toggle_mod if action == 'toggle' else self._remove_mod)()
                return

    def _filter_installed_mods(self, *_):
        if not self.current or not hasattr(self,'installed_filter'):
            return
        query = self.mods_search.text().casefold().strip()
        mode = self.installed_filter.currentIndex()
        records = {mod.filename:mod for mod in self.current.installed_mods}
        for index in range(self.mods.count()):
            item=self.mods.item(index);mod=records.get(item.data(Qt.UserRole))
            if not mod:
                continue
            local=not mod.project_id or mod.project_id.startswith('local:')
            match = mode==0 or mode==1 and mod.enabled or mode==2 and not mod.enabled or mode==3 and not local or mode==4 and local
            item.setHidden(not match or query not in (mod.name+' '+mod.filename).casefold())

    def _play_card(self, card):
        self._open_card(card)
        self._launch()

    def _open_card(self, card):
        identifier = card.data(Qt.UserRole)
        for index in range(self.instances.count()):
            if self.instances.item(index).data(Qt.UserRole) == identifier:
                self.instances.setCurrentRow(index)
                self.library_stack.setCurrentWidget(self.detail_surface)
                return

    def show_library(self):
        self.mod_catalog.leave()
        self.library_stack.setCurrentWidget(self.library)

    def _find_build(self):
        self.show_library()
        self.pack_search.setFocus()
        self.pack_search.selectAll()

    def open_mod_catalog(self):
        if self.current:
            self.library_stack.setCurrentWidget(self.mod_catalog)
            self.mod_catalog.open_for(self.current)

    def _close_catalog(self):
        self.mod_catalog.leave()
        self.library_stack.setCurrentWidget(self.detail_surface)

    def _catalog_install(self, instance_id, project_id):
        # Keep the original resolver, dependency confirmation, SHA-512 and backups.
        if self.mod_catalog.install_busy:
            queue = self.mod_catalog.install_queue
            key = (instance_id, project_id)
            if instance_id == self.mod_catalog.install_target and project_id in self.mod_catalog.install_projects:
                return
            if key in queue:
                queue.remove(key)
                self.mod_catalog.status.setText('Мод убран из очереди.')
            elif len(queue) < 12:
                queue.append(key)
                self.mod_catalog.status.setText('Добавлено в очередь. Для удаления нажми кнопку очереди ещё раз.')
            else:
                self.mod_catalog.status.setText('В очереди уже 12 модов. Дождись завершения установки.')
            self.mod_catalog._selection_changed(self.mod_catalog.results.currentRow())
            return
        self._catalog_install_target = instance_id
        self._catalog_batch_requested = None
        self._catalog_exact_version = False
        self.mod_catalog.set_install_busy(True, instance_id=instance_id, project_id=project_id)
        self.mod_catalog.status.setText('Проверяем совместимость и обязательные зависимости…')
        threading.Thread(target=self._resolve_install, args=(instance_id, project_id), daemon=True).start()

    def _catalog_install_batch(self, instance_id, projects):
        if self.mod_catalog.install_busy or not isinstance(projects,list) or not 1<=len(projects)<=20:
            return
        self._catalog_install_target=instance_id
        self._catalog_batch_requested=tuple(projects)
        self._catalog_exact_version=False
        self.mod_catalog.set_install_busy(True,instance_id=instance_id,phase='resolve',projects=projects)
        self.mod_catalog.status.setText('Собираем общий список модов и обязательных зависимостей…')
        def work():
            try:
                from nexus_launcher.mod_batch import resolve_batch
                instance=self.service.load(instance_id)
                plan=resolve_batch(self.provider,projects,instance.minecraft_version,instance.loader)
                self.bridge.plan_ready.emit(instance_id,projects[0],plan)
            except Exception as error:
                self.bridge.task_failed.emit(str(error))
        threading.Thread(target=work,daemon=True).start()

    def _catalog_install_version(self,instance_id,project_id,version_id):
        if self.mod_catalog.install_busy:return
        self._catalog_install_target=instance_id;self._catalog_batch_requested=None
        self._catalog_exact_version=True
        self.mod_catalog.set_install_busy(True,instance_id=instance_id,project_id=project_id)
        self.mod_catalog.status.setText('Проверяем выбранную версию и зависимости…')
        def work():
            try:
                from nexus_launcher.mod_batch import resolve_exact
                instance=self.service.load(instance_id)
                plan=resolve_exact(self.provider,project_id,version_id,instance.minecraft_version,instance.loader)
                self.bridge.plan_ready.emit(instance_id,project_id,plan)
            except Exception as error:self.bridge.task_failed.emit(str(error))
        threading.Thread(target=work,daemon=True).start()

    def _confirm_install(self, instance_id, project_id, plan):
        from .mod_install_confirmation import ModInstallConfirmation
        from PySide6.QtWidgets import QDialog
        try:
            instance = self.service.load(instance_id)
        except (OSError, ValueError) as error:
            self._task_failed(str(error))
            return
        requested=getattr(self,'_catalog_batch_requested',None)
        self.mod_catalog.set_install_busy(True, instance_id=instance_id, projects=requested or [project_id], phase='confirm')
        if ModInstallConfirmation(instance.name, project_id, plan, self, requested_projects=requested).exec() == QDialog.Accepted:
            self.mod_catalog.set_install_busy(True, instance_id=instance_id, phase='download', projects=[v['project_id'] for v in plan])
            self.mod_catalog.status.setText('Скачиваем и проверяем моды. Результат появится здесь.')
            worker=self._install_exact_worker if getattr(self,'_catalog_exact_version',False) else self._install_worker
            if getattr(self,'_catalog_exact_version',False):
                self._version_launch_owner=self.launch_owner if self.launch_owner is not None else self.window()
            threading.Thread(target=worker, args=(instance_id, project_id, plan), daemon=True).start()
        else:
            self._catalog_install_target = None
            self.mod_catalog.set_install_busy(False)
            self.mod_catalog.status.setText('Установка отменена. Файлы не изменены.')
            QTimer.singleShot(0, self._next_catalog_install)

    def _install_exact_worker(self,instance_id,project_id,plan):
        from nexus_launcher.diagnostic_trial import launcher_idle
        owner=getattr(self,'_version_launch_owner',None)
        try:
            with launcher_idle(owner):
                mods=self.installer.install(instance_id,project_id,resolved_versions=plan)
            self.bridge.task_done.emit(f'Версия изменена. Проверено файлов: {len(mods)}')
        except Exception as error:self.bridge.task_failed.emit(str(error))

    def _next_catalog_install(self):
        if self.mod_catalog.install_busy:
            return
        while self.mod_catalog.install_queue:
            instance_id, project_id = self.mod_catalog.install_queue.pop(0)
            try:
                instance = self.service.load(instance_id)
            except (OSError, ValueError):
                continue
            if any(mod.project_id == project_id for mod in instance.installed_mods):
                continue  # A previous plan may already have installed this dependency.
            self._catalog_install(instance_id, project_id)
            return
        self.mod_catalog._selection_changed(self.mod_catalog.results.currentRow())

    def _task_done(self, message):
        target = getattr(self, '_catalog_install_target', None)
        self._catalog_install_target = None
        if target:
            self.mod_catalog.refresh_installed(self.service.load(target))
        self.mod_catalog.set_install_busy(False)
        if self.current:
            visible=self.library_stack.currentWidget()
            tab=self.detail.currentIndex()
            scroll=self.detail_scroll.verticalScrollBar().value()
            self.refresh(self.current.id)
            self.library_stack.setCurrentWidget(visible)
            self.detail.setCurrentIndex(tab)
            self.detail_scroll.verticalScrollBar().setValue(scroll)
        self.mod_catalog.status.setText(message)
        self.library_status.setText(message)
        self.library_status.show()
        if target:
            QTimer.singleShot(0, self._next_catalog_install)

    def _task_failed(self, message):
        target = getattr(self, '_catalog_install_target', None)
        self._catalog_install_target = None
        self.mod_catalog.set_install_busy(False)
        self.mod_catalog.status.setText('Не удалось завершить операцию: ' + message)
        self.library_status.setText('Не удалось завершить операцию: ' + message)
        self.library_status.show()
        if target:
            QTimer.singleShot(0, self._next_catalog_install)

    def shutdown_catalog(self):
        self.installed_media.shutdown()
        self.mod_catalog.shutdown()
