"""Presentation-only library adapter; original instance operations are retained."""
import threading

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QLayout, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
    QMessageBox,
)

from nexus_launcher.instance_ui import InstancePage
from .mod_catalog import ModCatalog
from .artwork import ArtworkSurface
from .library_components import ArtworkCard, ArtworkGrid, InstalledModDelegate
from .content_state import ContentState
from .artwork import landscape
from PySide6.QtGui import QIcon


class PackLibraryPage(InstancePage):
    def _build(self):
        super()._build()
        # Keep original data selection/model, retire its duplicate visible library.
        self.setStyleSheet("")
        self.workspace.layout().itemAt(0).widget().hide()
        self.mods_search.setClearButtonEnabled(True)
        self.mods.setItemDelegate(InstalledModDelegate(self.mods))
        self.instance_title.setObjectName("pageTitle")
        self.instance_title.setWordWrap(True)
        self.instance_stats.setWordWrap(True)
        self.instance_stats.setObjectName("muted")
        self.launch_button.setObjectName("primaryAction")
        self.launch_button.setText("Играть")
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
        header = ArtworkSurface()
        self.build_hero = header
        header.setMinimumHeight(188)
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
        heading.setObjectName("pageTitle")
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
        self.library_empty = ArtworkSurface()
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
        empty_create.hide()
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
        search_tools.addWidget(self.mods_search, 1)
        search_tools.addWidget(updates)
        mod_panel.layout().insertLayout(0, search_tools)
        self.mods_empty = ContentState("Моды меняют правила игры.",
                                       "Найди дополнения для этой версии Minecraft или добавь свой JAR.",
                                       "Найти моды", lambda: self._create() if self.current and self.current.loader == "vanilla" else self.open_mod_catalog(), "mods")
        mod_panel.layout().insertWidget(1, self.mods_empty, 1)
        self._migrate_content_tabs()
        root.addWidget(self.library_stack)
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
            cell = QWidget()
            box = QVBoxLayout(cell)
            box.setContentsMargins(0, 8, 0, 8)
            label = QLabel(caption)
            label.setObjectName("muted")
            value = QLabel()
            value.setObjectName("cardTitle")
            value.setWordWrap(True)
            box.addWidget(label)
            box.addWidget(value)
            facts.addWidget(cell, index // 3, index % 3)
            self.overview_facts[caption] = value
        overview.insertLayout(1, facts)
        body.addWidget(content, 1)

    def _select(self, row):
        super()._select(row)
        if not self.current or not hasattr(self, "content_lists"):
            return
        root = self.service.path_for(self.current.id)
        self.build_hero.set_artwork(self.current.banner or self.current.icon, self.current.id)
        played = self.current.last_launch[:10] if self.current.last_launch else "Ещё не запускалась"
        self.last_played.setText(f"{len(self.current.installed_mods)} модов · {self.current.memory_mb / 1024:g} ГБ памяти · Последний запуск: {played}")
        self.mods_empty.setVisible(not self.mods.count())
        self.find_mods_action.setVisible(bool(self.mods.count()))
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
            item.setData(Qt.UserRole + 2, {'name': mod.name, 'filename': mod.filename,
                                        'metadata': f"{'Включён' if mod.enabled else 'Отключён'} · {source} · {self.current.minecraft_version} · {self.current.loader.title()}"})
            item.setIcon(QIcon(landscape(mod.project_id or mod.filename, 48, 48)))
            item.setSizeHint(QSize(200, 88))
        self.mods.setIconSize(QSize(48, 48))
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
            return
        self.mod_catalog.set_install_busy(True)
        threading.Thread(target=self._resolve_install, args=(instance_id, project_id), daemon=True).start()

    def _confirm_install(self, instance_id, project_id, plan):
        text = "Будут установлены мод и обязательные зависимости:\n" + "\n".join(
            str(version.get("name") or version["project_id"]) for version in plan
        )
        if QMessageBox.question(self, "Установить моды", text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes:
            threading.Thread(target=self._install_worker, args=(instance_id, project_id, plan), daemon=True).start()
        else:
            self.mod_catalog.set_install_busy(False)

    def _task_done(self, message):
        self.mod_catalog.set_install_busy(False)
        super()._task_done(message)

    def _task_failed(self, message):
        self.mod_catalog.set_install_busy(False)
        super()._task_failed(message)

    def shutdown_catalog(self):
        self.mod_catalog.shutdown()
