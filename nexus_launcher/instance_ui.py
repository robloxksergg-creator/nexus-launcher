from __future__ import annotations

import os
import threading
from pathlib import Path

from nexus_launcher.instance_transfer import InstanceTransferService
from nexus_launcher.modrinth_provider import ModInstaller, ModrinthProvider
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMenu,
    QMessageBox,
    QInputDialog,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from nexus_launcher.user_instances import InstanceService, UserInstance


class InstanceBridge(QObject):
    search_ready = Signal(object)
    plan_ready = Signal(str, str, object)
    task_done = Signal(str)
    task_failed = Signal(str)
    instance_ready = Signal(str, str)
    folder_analyzed = Signal(str, object)
    zip_analyzed = Signal(str, object)
    operation_progress = Signal(str)
    backup_analyzed = Signal(str, object)
    delete_analyzed = Signal(str, object)


from nexus_launcher.themed_dialog import NexusDialog


class CreateInstanceDialog(NexusDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новая сборка")
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit("Моя сборка")
        self.minecraft = QLineEdit("1.21.1")
        self.loader = QComboBox()
        self.loader.setToolTip("Загрузчик модов. Моды обычно требуют конкретный loader.")
        self.loader.addItems(["Fabric", "NeoForge", "Forge", "Vanilla"])
        self.loader_version = QLineEdit()
        self.loader_version.setPlaceholderText("Можно оставить пустым")
        self.loader_version.setToolTip("Пусто — Nexus выберет рекомендуемую версию, если она известна.")
        self.install_path = QLineEdit()
        self.install_path.setPlaceholderText("По умолчанию — NEXUS/user-instances/<id>")
        path_row = QHBoxLayout()
        path_row.addWidget(self.install_path, 1)
        browse_path = QPushButton("Обзор…")
        browse_path.clicked.connect(self._browse_path)
        path_row.addWidget(browse_path)
        self.icon_path = QLineEdit()
        self.icon_path.setPlaceholderText("Необязательно")
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.icon_path, 1)
        browse_icon = QPushButton("Выбрать…")
        browse_icon.clicked.connect(self._browse_icon)
        icon_row.addWidget(browse_icon)
        form.addRow("Название", self.name)
        form.addRow("Minecraft", self.minecraft)
        form.addRow("Загрузчик", self.loader)
        root.addLayout(form)
        from nexus_launcher.creator_services import TEMPLATES
        self.template = QComboBox()
        self.template.addItems(TEMPLATES)
        form.addRow("Шаблон (без предустановленных модов)", self.template)
        advanced_button = QPushButton("Дополнительные настройки ▾")
        advanced_button.setCheckable(True)
        root.addWidget(advanced_button)
        advanced = QWidget()
        advanced_form = QFormLayout(advanced)
        advanced_form.addRow("Версия загрузчика", self.loader_version)
        advanced_form.addRow("Папка установки", path_row)
        advanced_form.addRow("Иконка / artwork", icon_row)
        self.java = QLineEdit()
        self.memory = QSpinBox()
        self.memory.setRange(1024, 32768)
        self.memory.setValue(4096)
        self.memory.setSuffix(" МБ")
        self.jvm = QLineEdit()
        advanced_form.addRow("Java (пусто — автоматически)", self.java)
        advanced_form.addRow("Память", self.memory)
        advanced_form.addRow("JVM arguments", self.jvm)
        self.resolution_width, self.resolution_height = QSpinBox(), QSpinBox()
        self.resolution_width.setRange(0, 7680)
        self.resolution_height.setRange(0, 4320)
        self.resolution_width.setSpecialValueText("Авто")
        self.resolution_height.setSpecialValueText("Авто")
        advanced_form.addRow("Ширина игры", self.resolution_width)
        advanced_form.addRow("Высота игры", self.resolution_height)
        self.banner = QLineEdit()
        banner_row = QHBoxLayout()
        banner_row.addWidget(self.banner)
        browse_banner = QPushButton("Выбрать…")
        browse_banner.clicked.connect(self._browse_banner)
        banner_row.addWidget(browse_banner)
        advanced_form.addRow("Баннер", banner_row)
        root.addWidget(advanced)
        advanced.hide()
        advanced_button.toggled.connect(advanced.setVisible)
        def apply_template(name):
            template = TEMPLATES[name]
            index = self.loader.findText(template["loader"], Qt.MatchFixedString)
            self.loader.setCurrentIndex(index)
            self.memory.setValue(template["memory_mb"])
            self.loader_version.clear()
        self.template.currentTextChanged.connect(apply_template)
        apply_template(self.template.currentText())
        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        create = QPushButton("Создать")
        create.setObjectName("playLarge")
        create.clicked.connect(self.accept)
        actions.addWidget(cancel)
        actions.addWidget(create)
        root.addLayout(actions)

    def values(self):
        return (
            self.name.text(),
            self.minecraft.text(),
            self.loader.currentText().lower(),
            self.loader_version.text(),
            self.install_path.text().strip(),
        )

    def accept(self):
        width, height = self.resolution_width.value(), self.resolution_height.value()
        if (width or height) and not (width >= 320 and height >= 240):
            QMessageBox.warning(self, "Разрешение", "Укажите обе стороны от 320 × 240 или оставьте обе в режиме Авто.")
            return
        super().accept()

    def apply_options(self, instance):
        instance.memory_mb = self.memory.value()
        instance.java_path = self.java.text().strip()
        instance.jvm_args = self.jvm.text().split()
        instance.resolution_width = self.resolution_width.value()
        instance.resolution_height = self.resolution_height.value()
        instance.icon = self.icon_path.text().strip()
        instance.banner = self.banner.text().strip()

    def _browse_banner(self):
        value, _ = QFileDialog.getOpenFileName(self, "Баннер", "", "Изображения (*.png *.jpg *.jpeg *.webp)")
        if value:
            self.banner.setText(value)

    def _browse_path(self):
        value = QFileDialog.getExistingDirectory(self, "Папка новой сборки", self.install_path.text())
        if value:
            self.install_path.setText(value)

    def _browse_icon(self):
        value, _ = QFileDialog.getOpenFileName(self, "Иконка сборки", "", "Изображения (*.png *.jpg *.jpeg *.webp)")
        if value:
            self.icon_path.setText(value)


class InstancePage(QWidget):
    launch_requested = Signal(str)

    def __init__(self, service: InstanceService, parent=None):
        super().__init__(parent)
        self.service = service
        self.provider = ModrinthProvider()
        self.installer = ModInstaller(service, self.provider)
        self.transfer = InstanceTransferService(service)
        self.bridge = InstanceBridge()
        self.bridge.plan_ready.connect(self._confirm_install)
        self.bridge.search_ready.connect(self._show_search)
        self.bridge.task_done.connect(self._task_done)
        self.bridge.task_failed.connect(self._task_failed)
        self.bridge.instance_ready.connect(lambda identifier, message: (self.refresh(identifier), QMessageBox.information(self, "NEXUS Launcher", message)))
        self.bridge.folder_analyzed.connect(self._confirm_folder_import)
        self.bridge.zip_analyzed.connect(self._confirm_zip_import)
        self.bridge.operation_progress.connect(lambda message: self.instance_stats.setText(message))
        self.bridge.backup_analyzed.connect(self._confirm_backup)
        self.bridge.delete_analyzed.connect(self._confirm_physical_delete)
        self.current: UserInstance | None = None
        self.search_results = []
        self.backup_retention = 5
        self._build()
        self.refresh()

    def _build(self):
        self.setObjectName("instancePage")
        self.setStyleSheet("""
            QWidget#instancePage { background:transparent; color:#edf5ff; }
            QFrame#instanceWarning { background:#211a11; border:1px solid #674d27; border-radius:8px; }
            QLabel#instanceWarningTitle { color:#e8b866; font-size:10px; font-weight:800; letter-spacing:2px; }
            QFrame#instanceWorkspace { background:#080e17; border:1px solid #1b293a; border-radius:12px; }
            QFrame#instanceEmpty { background:transparent; border:0; }
            QListWidget#instanceList { background:#080e17; border:0; border-right:1px solid #1b293a; border-radius:11px; padding:10px 8px; outline:none; }
            QListWidget#instanceList::item { color:#b7c5d6; min-height:56px; padding:9px 11px; border-radius:8px; }
            QListWidget#instanceList::item:hover { background:#111f30; color:white; }
            QListWidget#instanceList::item:selected { background:#173653; color:white; border-left:2px solid #68bdf2; }
            QTabWidget#instanceTabs::pane { background:#0a111b; border:0; border-top:1px solid #1d2d41; top:-1px; }
            QTabBar::tab { background:transparent; color:#8fa1b7; border:0; border-bottom:2px solid transparent; padding:12px 17px; min-width:86px; }
            QTabBar::tab:hover { color:white; background:#101b29; }
            QTabBar::tab:selected { color:white; border-bottom-color:#63b7ef; background:#0e1926; }
            QLabel#instancePageTitle { font-family:'Georgia'; font-size:31px; font-weight:700; letter-spacing:4px; }
            QLabel#instanceName { font-family:'Georgia'; font-size:28px; font-weight:700; letter-spacing:1px; }
            QLabel#instanceStats { color:#a9bbce; font-size:14px; line-height:1.4; }
            QLabel#emptyGlyph { color:#69b9ec; font-size:42px; }
            QLabel#emptyTitle { color:white; font-family:'Georgia'; font-size:27px; font-weight:700; }
            QPushButton { background:#101925; border:1px solid #26384d; border-radius:8px; padding:9px 14px; }
            QPushButton:hover { background:#17263a; border-color:#4c8ec5; }
            QPushButton:pressed { background:#0b121c; border-color:#315d82; }
            QPushButton#playLarge, QPushButton#instanceCreate { background:#e8f4ff; color:#07111e; border:1px solid white; font-weight:800; letter-spacing:1px; }
            QPushButton#playLarge:hover, QPushButton#instanceCreate:hover { background:white; }
            QPushButton[focusVisible="true"], QLineEdit[focusVisible="true"], QComboBox[focusVisible="true"],
            QSpinBox[focusVisible="true"], QListWidget[focusVisible="true"], QTabBar[focusVisible="true"] { border:2px solid #8ad1ff; }
            QLineEdit, QComboBox, QSpinBox, QListWidget { background:#0a111b; color:#edf5ff; border:1px solid #223348; border-radius:8px; padding:9px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 32)
        root.setSpacing(14)
        title = QLabel("СБОРКИ")
        title.setObjectName("instancePageTitle")
        root.addWidget(title)
        subtitle = QLabel("Личные изолированные версии Minecraft и моды")
        subtitle.setObjectName("muted")
        root.addWidget(subtitle)

        warning = QFrame()
        warning.setObjectName("instanceWarning")
        warning.setMaximumWidth(620)
        warning_row = QHBoxLayout(warning)
        warning_row.setContentsMargins(13, 9, 13, 9)
        warning_title = QLabel("PRIVATE TEST")
        warning_title.setObjectName("instanceWarningTitle")
        warning_copy = QLabel("Изменения пользовательских сборок сохраняются локально.")
        warning_copy.setObjectName("muted")
        warning_row.addWidget(warning_title)
        warning_row.addWidget(warning_copy)
        root.addWidget(warning)

        self.page_state = QStackedWidget()
        root.addWidget(self.page_state, 1)
        self.empty_state = QFrame()
        self.empty_state.setObjectName("instanceEmpty")
        empty = QVBoxLayout(self.empty_state)
        empty.setContentsMargins(32, 32, 32, 70)
        empty.addStretch()
        glyph = QLabel("◇")
        glyph.setObjectName("emptyGlyph")
        glyph.setAlignment(Qt.AlignCenter)
        empty_title = QLabel("Создайте свой первый мир")
        empty_title.setObjectName("emptyTitle")
        empty_title.setAlignment(Qt.AlignCenter)
        empty_copy = QLabel("Создайте отдельную Minecraft-сборку, выберите версию, загрузчик и моды.")
        empty_copy.setObjectName("muted")
        empty_copy.setAlignment(Qt.AlignCenter)
        empty_copy.setWordWrap(True)
        create_empty = QPushButton("+ СОЗДАТЬ СБОРКУ")
        create_empty.setObjectName("instanceCreate")
        create_empty.setFixedSize(220, 46)
        create_empty.clicked.connect(self._create)
        import_empty = QPushButton("Импортировать ZIP")
        import_empty.setFixedWidth(220)
        import_empty.clicked.connect(self._import_zip)
        empty.addWidget(glyph)
        empty.addWidget(empty_title)
        empty.addWidget(empty_copy)
        empty.addSpacing(12)
        empty.addWidget(create_empty, 0, Qt.AlignHCenter)
        empty.addWidget(import_empty, 0, Qt.AlignHCenter)
        empty.addStretch()
        self.page_state.addWidget(self.empty_state)

        self.workspace = QFrame()
        self.workspace.setObjectName("instanceWorkspace")
        body = QHBoxLayout(self.workspace)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        left_widget = QWidget()
        left_widget.setFixedWidth(285)
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(10, 12, 10, 12)
        self.instances = QListWidget()
        self.instances.setObjectName("instanceList")
        self.instances.currentRowChanged.connect(self._select)
        left.addWidget(self.instances, 1)
        library_search = QLineEdit()
        library_search.setPlaceholderText("Найти сборку…")
        library_search.textChanged.connect(lambda text: self._filter_list(self.instances, text))
        left.insertWidget(0, library_search)
        import_folder = QPushButton("Импорт папки…")
        import_folder.clicked.connect(self._import_folder)
        left.addWidget(import_folder)
        create = QPushButton("+ Создать сборку")
        create.setObjectName("instanceCreate")
        create.clicked.connect(self._create)
        import_zip = QPushButton("Импортировать ZIP")
        import_zip.clicked.connect(self._import_zip)
        left.addWidget(create)
        left.addWidget(import_zip)
        body.addWidget(left_widget)

        self.detail = QTabWidget()
        self.detail.setObjectName("instanceTabs")
        body.addWidget(self.detail, 1)
        self.overview = QWidget()
        overview = QVBoxLayout(self.overview)
        overview.setContentsMargins(28, 24, 28, 28)
        overview.setSpacing(10)
        top = QHBoxLayout()
        titles = QVBoxLayout()
        self.instance_title = QLabel("Выберите сборку")
        self.instance_title.setObjectName("instanceName")
        self.instance_meta = QLabel()
        self.instance_meta.setObjectName("muted")
        titles.addWidget(self.instance_title)
        titles.addWidget(self.instance_meta)
        top.addLayout(titles, 1)
        self.context_button = QPushButton("•••")
        self.context_button.setFixedSize(52, 40)
        self.context_button.clicked.connect(self._open_context_menu)
        top.addWidget(self.context_button)
        overview.addLayout(top)
        self.instance_stats = QLabel()
        self.instance_stats.setObjectName("instanceStats")
        overview.addWidget(self.instance_stats)
        overview.addStretch()
        self.launch_button = QPushButton("ИГРАТЬ")
        self.launch_button.setObjectName("playLarge")
        self.launch_button.setFixedSize(220, 50)
        self.launch_button.clicked.connect(self._launch)
        overview.addWidget(self.launch_button, 0, Qt.AlignLeft)
        self.detail.addTab(self.overview, "Обзор")

        mods = QWidget()
        mods_layout = QVBoxLayout(mods)
        self.mods = QListWidget()
        self.mods_search = QLineEdit()
        self.mods_search.setPlaceholderText("Найти установленный мод…")
        self.mods_search.textChanged.connect(lambda text: self._filter_list(self.mods, text))
        self.mods.setSelectionMode(QAbstractItemView.ExtendedSelection)
        mod_header = QHBoxLayout()
        mod_header.addWidget(self.mods_search, 1)
        diagnostics = QPushButton("Диагностика сборки")
        diagnostics.clicked.connect(self._open_diagnostics)
        mod_header.addWidget(diagnostics)
        mods_layout.addLayout(mod_header)
        mods_layout.addWidget(self.mods)
        mod_actions = QHBoxLayout()
        for label, handler in (("Включить / отключить", self._toggle_mod), ("Удалить мод", self._remove_mod), ("Добавить JAR", self._import_jar), ("Открыть папку", self._open_mods)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            mod_actions.addWidget(button)
        mod_actions.addStretch()
        mods_layout.addLayout(mod_actions)
        self.detail.addTab(mods, "Моды")

        catalog = QWidget()
        catalog_layout = QVBoxLayout(catalog)
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Поиск на Modrinth")
        search = QPushButton("Найти")
        search.clicked.connect(self._search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(search)
        catalog_layout.addLayout(search_row)
        self.catalog = QListWidget()
        catalog_layout.addWidget(self.catalog)
        install = QPushButton("Установить выбранный мод и зависимости")
        install.clicked.connect(self._install)
        updates = QPushButton("Проверить обновления модов")
        updates.clicked.connect(self._update_mods)
        catalog_layout.addWidget(install)
        catalog_layout.addWidget(updates)
        self.detail.addTab(catalog, "Modrinth")

        files = QWidget()
        files_layout = QGridLayout(files)
        for index, (label, relative) in enumerate((("Ресурс-паки", "resourcepacks"), ("Шейдеры", "shaderpacks"), ("Скриншоты", "screenshots"), ("Конфигурация", "config"), ("Логи", "logs"), ("Миры", "saves"))):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, path=relative: self._open_relative(path))
            files_layout.addWidget(button, index // 2, index % 2)
        self.detail.addTab(files, "Файлы")

        settings = QWidget()
        form = QFormLayout(settings)
        self.memory = QSpinBox()
        self.memory.setRange(1024, 32768)
        self.memory.setSingleStep(512)
        self.java = QLineEdit()
        self.jvm = QLineEdit()
        self.install_path = QLineEdit()
        self.install_path.setReadOnly(True)
        path_actions = QHBoxLayout()
        change_path = QPushButton("Изменить папку")
        change_path.clicked.connect(self._change_path)
        open_path = QPushButton("Открыть")
        open_path.clicked.connect(self._open_instance)
        path_actions.addWidget(change_path)
        path_actions.addWidget(open_path)
        save = QPushButton("Сохранить параметры")
        save.clicked.connect(self._save_settings)
        form.addRow("Память, МБ", self.memory)
        form.addRow("Java", self.java)
        form.addRow("JVM аргументы", self.jvm)
        form.addRow("Папка установки", self.install_path)
        form.addRow("", path_actions)
        form.addRow(save)
        self.detail.addTab(settings, "Настройки")

        history = QWidget()
        history_layout = QVBoxLayout(history)
        self.history = QListWidget()
        history_layout.addWidget(self.history)
        self.detail.addTab(history, "Логи")
        backups = QWidget()
        backups_layout = QVBoxLayout(backups)
        self.backups_list = QListWidget()
        backups_layout.addWidget(self.backups_list)
        backup_actions = QHBoxLayout()
        for label, callback in (("Создать", self._backup), ("Восстановить как новую сборку", self._restore_selected_backup),
                                ("Удалить", self._delete_selected_backup), ("Открыть папку", lambda: self._open_relative(".nexus/backups"))):
            button = QPushButton(label); button.clicked.connect(callback); backup_actions.addWidget(button)
        backups_layout.addLayout(backup_actions)
        backups_layout.addWidget(QLabel("Хранятся 5 последних копий. При создании шестой самая старая удаляется."))
        self.detail.addTab(backups, "Резервные копии")
        self.page_state.addWidget(self.workspace)

    def refresh(self, select_id=""):
        items = self.service.list()
        self.instances.clear()
        selected = -1
        for index, item in enumerate(items):
            mod_label = f"{len(item.installed_mods)} модов" if item.installed_mods else "Без модов"
            self.instances.addItem(f"{item.name}\n{item.loader.title()} · {item.minecraft_version}  ·  {mod_label}")
            self.instances.item(index).setData(Qt.UserRole, item.id)
            if item.id == select_id:
                selected = index
        if items:
            self.page_state.setCurrentWidget(self.workspace)
            self.instances.setCurrentRow(max(0, selected))
        else:
            self.current = None
            self.instance_title.setText("Создайте первую сборку")
            self.instance_meta.clear()
            self.instance_stats.clear()
            self.mods.clear()
            self.launch_button.hide()
            self.context_button.hide()
            self.page_state.setCurrentWidget(self.empty_state)

    def _select(self, row):
        if row < 0 or row >= self.instances.count():
            self.current = None
            self.launch_button.hide()
            self.context_button.hide()
            return
        self.current = self.service.load(self.instances.item(row).data(Qt.UserRole))
        self.instance_title.setText(self.current.name)
        self.instance_meta.setText(
            f"Minecraft {self.current.minecraft_version} · {self.current.loader.title()} {self.current.loader_version}".strip()
        )
        enabled_mods = sum(1 for mod in self.current.installed_mods if mod.enabled)
        folder = self.service.path_for(self.current.id)
        resource_count = sum(1 for p in (folder / "resourcepacks").glob("*"))
        shader_count = sum(1 for p in (folder / "shaderpacks").glob("*"))
        self.instance_stats.setText(
            f"{len(self.current.installed_mods)} модов · {enabled_mods} включено\n"
            f"Ресурспаки: {resource_count} · Шейдеры: {shader_count}\n"
            f"Память: {self.current.memory_mb / 1024:g} ГБ\n"
            f"Последний запуск: {self.current.last_launch or 'ещё не запускалась'}\n"
            f"Папка: {self.service.path_for(self.current.id)}"
        )
        self.launch_button.show()
        self.context_button.show()
        self.memory.setValue(self.current.memory_mb)
        self.java.setText(self.current.java_path)
        self.jvm.setText(" ".join(self.current.jvm_args))
        self.install_path.setText(str(self.service.path_for(self.current.id)))
        self.mods.clear()
        for mod in self.current.installed_mods:
            self.mods.addItem(("● " if mod.enabled else "○ ") + mod.name)
            self.mods.item(self.mods.count() - 1).setData(Qt.UserRole, mod.filename)
        self._load_history()
        self._load_backups()

    def _load_backups(self):
        self.backups_list.clear()
        if not self.current: return
        from nexus_launcher.instance_backups import BackupService
        for path in BackupService(self.service).list(self.current.id):
            stat = path.stat()
            self.backups_list.addItem(f"{path.name}\n{stat.st_size / 1048576:.1f} МБ")
            self.backups_list.item(self.backups_list.count() - 1).setData(Qt.UserRole, path.name)

    def _restore_selected_backup(self):
        item = self.backups_list.currentItem()
        if not self.current or not item: return
        threading.Thread(target=self._restore_worker, args=(self.current.id, item.data(Qt.UserRole)), daemon=True).start()

    def _restore_worker(self, instance_id, filename):
        try:
            from nexus_launcher.instance_backups import BackupService
            restored = BackupService(self.service).restore_copy(instance_id, filename)
            self.bridge.instance_ready.emit(restored.id, "Копия восстановлена в отдельную сборку.")
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _delete_selected_backup(self):
        item = self.backups_list.currentItem()
        if not self.current or not item: return
        if QMessageBox.question(self, "Удаление копии", "Удалить выбранную резервную копию?") != QMessageBox.Yes: return
        try:
            from nexus_launcher.instance_backups import BackupService
            BackupService(self.service).delete(self.current.id, item.data(Qt.UserRole))
            self._load_backups()
        except Exception as error: self._task_failed(str(error))

    def _open_context_menu(self):
        if not self.current:
            return
        menu = QMenu(self)
        menu.addAction("Переименовать", self._rename)
        menu.addAction("Дублировать", self._duplicate)
        menu.addAction("Экспортировать ZIP", self._export_zip)
        menu.addAction("Резервная копия", self._backup)
        menu.addAction("Восстановить копию как новую сборку…", self._restore_backup)
        menu.addAction("Удалить резервную копию…", self._delete_backup)
        menu.addAction("Открыть резервные копии", lambda: self._open_relative(".nexus/backups"))
        menu.addAction("Открыть папку сборки", self._open_instance)
        menu.addSeparator()
        menu.addAction("Убрать из библиотеки (сохранить файлы)", self._forget)
        menu.addAction("Удалить файлы сборки…", self._delete)
        menu.exec(self.context_button.mapToGlobal(self.context_button.rect().bottomRight()))

    def _create(self):
        dialog = CreateInstanceDialog(self)
        if dialog.exec():
            try:
                instance = self.service.create(*dialog.values())
                dialog.apply_options(instance)
                self.service.save(instance)
                self.refresh(instance.id)
            except Exception as error:
                QMessageBox.warning(self, "NEXUS Launcher", str(error))

    def _forget(self):
        if self.current:
            self.service.forget(self.current.id)
            self.refresh()

    def _delete(self):
        if not self.current:
            return
        threading.Thread(target=self._analyze_delete_worker, args=(self.current.id,), daemon=True).start()

    def _analyze_delete_worker(self, instance_id):
        try: self.bridge.delete_analyzed.emit(instance_id, self.service.disk_summary(instance_id))
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _confirm_physical_delete(self, instance_id, summary):
        message = (f"Будет удалено:\n{summary['path']}\n\nРазмер: {summary['bytes'] / 1073741824:.2f} ГБ\n"
                   f"Миры сохранения: {summary['saves']}\n\nЭто действие нельзя отменить.")
        if QMessageBox.question(self, "Удалить файлы с диска", message) != QMessageBox.Yes: return
        threading.Thread(target=self._delete_worker, args=(instance_id,), daemon=True).start()

    def _delete_worker(self, instance_id):
        try:
            self.service.delete(instance_id)
            self.bridge.instance_ready.emit("", "Файлы сборки удалены.")
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _rename(self):
        if not self.current:
            return
        name, accepted = QInputDialog.getText(self, "Переименовать сборку", "Новое название", text=self.current.name)
        if accepted:
            try:
                self.current = self.service.rename(self.current.id, name)
                self.refresh(self.current.id)
            except Exception as error:
                self._task_failed(str(error))

    def _duplicate(self):
        if not self.current:
            return
        try:
            duplicate = self.service.duplicate(self.current.id)
            self.refresh(duplicate.id)
        except Exception as error:
            self._task_failed(str(error))

    def _import_zip(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Импорт сборки", "", "ZIP (*.zip)")
        if not filename:
            return
        threading.Thread(target=self._analyze_zip_worker, args=(filename,), daemon=True).start()

    def _analyze_zip_worker(self, filename):
        try: self.bridge.zip_analyzed.emit(filename, self.transfer.analyze_zip(Path(filename)))
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _confirm_zip_import(self, filename, summary):
        try:
            text = f"Minecraft: {summary['minecraft'] or 'не определён (будет 1.21.1)'}\nЗагрузчик: {summary['loader'] or 'не определён (будет Fabric)'}\nМодов: {summary['mods']}\nРазмер: {summary['bytes'] / 1048576:.1f} МБ\nИмпортировать в новую сборку?"
            if QMessageBox.question(self, "Анализ ZIP", text) != QMessageBox.Yes:
                return
            threading.Thread(target=self._import_zip_worker, args=(filename,), daemon=True).start()
        except Exception as error:
            self._task_failed(str(error))

    def _import_zip_worker(self, filename):
        try:
            instance = self.transfer.import_zip(Path(filename))
            self.bridge.instance_ready.emit(instance.id, "ZIP импортирован в новую сборку.")
        except Exception as error: self.bridge.task_failed.emit(str(error))

    @staticmethod
    def _filter_list(widget, text):
        for index in range(widget.count()):
            item = widget.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def _import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Папка Minecraft для копирования")
        if not folder:
            return
        threading.Thread(target=self._analyze_folder_worker, args=(folder,), daemon=True).start()

    def _analyze_folder_worker(self, folder):
        try: self.bridge.folder_analyzed.emit(folder, self.transfer.analyze_folder(Path(folder)))
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _confirm_folder_import(self, folder, summary):
        try:
            dialog = CreateInstanceDialog(self)
            dialog.setWindowTitle(f"Импорт копии · {summary['mods']} модов · {summary['bytes'] / 1048576:.1f} МБ")
            dialog.name.setText(Path(folder).name)
            if summary['minecraft']:
                dialog.minecraft.setText(summary['minecraft'])
            if summary['loader']:
                dialog.loader.setCurrentIndex(dialog.loader.findText(summary['loader'], Qt.MatchFixedString))
                dialog.loader_version.setText(summary['loader_version'])
            dialog.install_path.setEnabled(False)
            if dialog.exec():
                values = dialog.values()
                destination = self.service.root
                review = (f"Найдено:\nMinecraft: {values[1]}\nLoader: {values[2]} {values[3]}\nМодов: {summary['mods']}\n"
                          f"Размер: {summary['bytes']/1048576:.1f} МБ\nDestination: {destination}\n\nИсходная папка не изменяется. Начать копирование?")
                if QMessageBox.question(self, "Импорт папки", review) == QMessageBox.Yes:
                    threading.Thread(target=self._import_folder_worker, args=(folder, values[:4]), daemon=True).start()
        except Exception as error:
            self._task_failed(str(error))

    def _import_folder_worker(self, folder, values):
        try:
            instance = self.transfer.import_folder(Path(folder), *values,
                progress=lambda current, done, total: self.bridge.operation_progress.emit(f"Копирование файлов…\n{current}\n{done} / {total}"))
            self.bridge.instance_ready.emit(instance.id, "Папка скопирована в новую сборку.")
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _export_zip(self):
        if not self.current:
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Экспорт сборки", f"{self.current.name}.zip", "ZIP (*.zip)")
        if filename:
            try:
                self.transfer.export_zip(self.current.id, Path(filename))
                self._task_done("Сборка экспортирована.")
            except Exception as error:
                self._task_failed(str(error))

    def _backup(self):
        if self.current:
            threading.Thread(target=self._analyze_backup_worker, args=(self.current.id,), daemon=True).start()

    def _analyze_backup_worker(self, instance_id):
        try: self.bridge.backup_analyzed.emit(instance_id, self.service.disk_summary(instance_id))
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _confirm_backup(self, instance_id, summary):
        if summary["bytes"] > 2 * 1024**3 and QMessageBox.question(self, "Большая резервная копия", f"Размер исходных файлов {summary['bytes']/1073741824:.1f} ГБ. Создать копию?\nХранятся 5 последних копий; при превышении лимита самая старая удаляется.") != QMessageBox.Yes:
            return
        threading.Thread(target=self._backup_worker, args=(instance_id,), daemon=True).start()

    def _backup_worker(self, instance_id):
        try:
            from nexus_launcher.instance_backups import BackupService
            path = BackupService(self.service).create(instance_id, retain=self.backup_retention)
            self.bridge.task_done.emit(f"Копия создана: {path.name}. Хранятся {self.backup_retention} последних копий.")
        except Exception as error: self.bridge.task_failed.emit(str(error))

    def _restore_backup(self):
        if not self.current:
            return
        from nexus_launcher.instance_backups import BackupService
        backups = BackupService(self.service)
        names = [path.name for path in backups.list(self.current.id)]
        if not names:
            self._task_done("Резервных копий пока нет.")
            return
        name, accepted = QInputDialog.getItem(self, "Восстановление", "Будет создана отдельная сборка; текущие файлы сохранятся.", names, 0, False)
        if accepted:
            threading.Thread(target=self._restore_worker, args=(self.current.id, name), daemon=True).start()

    def _delete_backup(self):
        if not self.current:
            return
        from nexus_launcher.instance_backups import BackupService
        backups = BackupService(self.service)
        names = [p.name for p in backups.list(self.current.id)]
        if not names:
            self._task_done("Резервных копий пока нет.")
            return
        name, accepted = QInputDialog.getItem(self, "Удаление копии", "Выберите резервную копию", names, 0, False)
        if accepted and QMessageBox.question(self, "Удаление копии", "Удалить " + name + "?") == QMessageBox.Yes:
            try:
                backups.delete(self.current.id, name)
            except Exception as error:
                self._task_failed(str(error))

    def _import_jar(self):
        if not self.current:
            return
        filenames, _ = QFileDialog.getOpenFileNames(self, "Локальные моды", "", "Minecraft mods (*.jar)")
        if filenames:
            try:
                for filename in filenames:
                    self.transfer.import_jar(self.current.id, Path(filename))
                self._task_done(f"Добавлено модов: {len(filenames)}.")
            except Exception as error:
                self._task_failed(str(error))

    def _open_mods(self):
        if not self.current:
            return
        folder = self.service.path_for(self.current.id) / "mods"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _open_diagnostics(self):
        if self.current is None:
            return
        from nexus_launcher.nexus_platform.instance_diagnostics_dialog import InstanceDiagnosticsDialog
        from nexus_launcher.diagnostic_trial import DiagnosticTrials, launcher_idle
        source_id = self.current.id
        owner = self.window()
        trials = DiagnosticTrials(self.service, source_id, lambda: launcher_idle(owner))
        dialog = InstanceDiagnosticsDialog(self.service.path_for(source_id), self.current.loader, self.current.name, self, trials=trials)
        dialog.exec()
        if dialog.trial_result:
            self.refresh(dialog.selected_instance_id or source_id)

    def _open_instance(self):
        if self.current:
            os.startfile(str(self.service.path_for(self.current.id)))

    def _open_relative(self, relative):
        if not self.current:
            return
        folder = self.service.path_for(self.current.id) / relative
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def _change_path(self):
        if not self.current:
            return
        destination = QFileDialog.getExistingDirectory(
            self, "Новая папка сборки", str(self.service.path_for(self.current.id).parent)
        )
        if not destination:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Изменение папки сборки")
        box.setText(f"«{self.current.name}» уже существует. Что сделать с файлами?")
        move = box.addButton("Переместить файлы", QMessageBox.AcceptRole)
        fresh = box.addButton("Использовать новую установку", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in {move, fresh}:
            return
        try:
            self.current = self.service.relocate(self.current.id, destination, box.clickedButton() is move)
            self.refresh(self.current.id)
        except Exception as error:
            self._task_failed(str(error))

    def _launch(self):
        if self.current:
            self.launch_requested.emit(self.current.id)

    def _save_settings(self):
        if not self.current:
            return
        self.current.memory_mb = self.memory.value()
        self.current.java_path = self.java.text().strip()
        self.current.jvm_args = self.jvm.text().split()
        self.service.save(self.current)
        QMessageBox.information(self, "NEXUS Launcher", "Параметры сохранены.")

    def _toggle_mod(self):
        item = self.mods.currentItem()
        if not self.current or not item:
            return
        mod = next((mod for mod in self.current.installed_mods if mod.filename == item.data(Qt.UserRole)), None)
        if mod:
            self.current = self.service.set_mod_enabled(self.current.id, mod.filename, not mod.enabled)
            self._select(self.instances.currentRow())

    def _remove_mod(self):
        items = self.mods.selectedItems()
        if not self.current or not items:
            return
        if (
            QMessageBox.question(self, "Удаление", f"Удалить выбранные моды ({len(items)}) из сборки?")
            != QMessageBox.Yes
        ):
            return
        for item in items:
            self.current = self.service.remove_mod(self.current.id, item.data(Qt.UserRole))
        self._select(self.instances.currentRow())

    def _search(self):
        if not self.current:
            return
        query, instance = self.query.text().strip(), self.current
        threading.Thread(target=self._search_worker, args=(query, instance), daemon=True).start()

    def _search_worker(self, query, instance):
        try:
            self.bridge.search_ready.emit(self.provider.search(query, instance.minecraft_version, instance.loader))
        except Exception as error:
            self.bridge.task_failed.emit(str(error))

    def _show_search(self, results):
        self.search_results = results
        self.catalog.clear()
        for result in results:
            self.catalog.addItem(f"{result.title}\n{result.description}")

    def _install(self):
        row = self.catalog.currentRow()
        if not self.current or row < 0:
            return
        project = self.search_results[row]
        threading.Thread(target=self._resolve_install, args=(self.current.id, project.project_id), daemon=True).start()

    def _resolve_install(self, instance_id, project_id):
        try:
            instance = self.service.load(instance_id)
            plan = self.provider.resolve(project_id, instance.minecraft_version, instance.loader)
            self.bridge.plan_ready.emit(instance_id, project_id, plan)
        except Exception as error:
            self.bridge.task_failed.emit(str(error))

    def _confirm_install(self, instance_id, project_id, plan):
        text = "Будут установлены мод и обязательные зависимости:\n" + "\n".join(str(v.get("name") or v["project_id"]) for v in plan)
        if QMessageBox.question(self, "Установить всё", text) == QMessageBox.Yes:
            threading.Thread(target=self._install_worker, args=(instance_id, project_id, plan), daemon=True).start()

    def _install_worker(self, instance_id, project_id, plan=None):
        try:
            mods = self.installer.install(instance_id, project_id, resolved_versions=plan)
            self.bridge.task_done.emit(f"Установлено модов: {len(mods)}")
        except Exception as error:
            self.bridge.task_failed.emit(str(error))

    def _update_mods(self):
        if self.current:
            threading.Thread(target=self._update_worker, args=(self.current.id,), daemon=True).start()

    def _update_worker(self, instance_id):
        try:
            updates = self.installer.available_updates(instance_id)
            if not updates:
                self.bridge.task_done.emit("Все моды уже актуальны.")
                return
            completed = self.installer.update_all(instance_id)
            self.bridge.task_done.emit(f"Обновлено модов: {len(completed)}")
        except Exception as error:
            self.bridge.task_failed.emit(str(error))

    def _load_history(self):
        self.history.clear()
        if not self.current:
            return
        path = self.service.path_for(self.current.id) / ".nexus" / "operations.jsonl"
        if not path.is_file():
            return
        import json

        for line in reversed(path.read_text(encoding="utf-8").splitlines()[-200:]):
            try:
                entry = json.loads(line)
                self.history.addItem(f"{entry.get('time', '')}  •  {entry.get('action', '')}")
            except json.JSONDecodeError:
                continue

    def _task_done(self, message):
        if self.current:
            self.refresh(self.current.id)
        QMessageBox.information(self, "NEXUS Launcher", message)

    def _task_failed(self, message):
        QMessageBox.warning(self, "NEXUS Launcher", message)
