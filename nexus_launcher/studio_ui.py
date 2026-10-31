from nexus_launcher.platform_support import open_in_file_manager
from pathlib import Path
import os
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPlainTextEdit, QPushButton, QListWidget, QFormLayout, QMessageBox, QFileDialog, QStackedWidget, QScrollArea, QGridLayout, QMenu, QTabWidget, QApplication)

from nexus_launcher.creator_services import Capabilities, StudioService, SIDES
from nexus_launcher.publishing import LocalSubmissionRepository, PublishingService


class StudioPage(QWidget):
    test_launch_requested = Signal(str)
    operation_done = Signal(str)
    operation_failed = Signal(str)

    def __init__(self, instances, parent=None):
        super().__init__(parent)
        self.service = StudioService(instances, Capabilities())
        self.submissions = LocalSubmissionRepository(instances.root / ".nexus-submissions")
        self.identifier = None
        self.dirty = False
        self.project = {}
        self.preview_page = None
        self.busy = False
        self.operation_done.connect(self._operation_done)
        self.operation_failed.connect(self._operation_failed)
        outer = QVBoxLayout(self)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack)
        workspace = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(workspace)
        self.stack.addWidget(scroll)
        root = QVBoxLayout(workspace)
        title = QLabel("NEXUS STUDIO · ЛОКАЛЬНЫЕ ПРОЕКТЫ")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        from nexus_launcher.nexus_platform.catalog_controls import NexusButton
        creator = NexusButton("NEXUS Creator · Холст")
        creator.clicked.connect(lambda: self.open_creator(False))
        academy = NexusButton("NEXUS Creator Academy")
        academy.clicked.connect(lambda: self.open_creator(True))
        root.addWidget(creator)
        root.addWidget(academy)
        self.creator_workspace = None
        root.addWidget(QLabel("Проекты используют сборки библиотеки. Здесь готовится локальный submission package; публикацию выполняет только будущий trusted backend."))
        self.stats = QLabel("Создайте проект или импортируйте сборку в библиотеку.")
        root.addWidget(self.stats)
        self.dirty_label = QLabel("Локальный черновик")
        self.dirty_label.setObjectName("muted")
        root.addWidget(self.dirty_label)
        create = QPushButton("+ Новый проект")
        create.clicked.connect(self.create_project)
        root.addWidget(create)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти проект…")
        self.search.textChanged.connect(self._filter)
        root.addWidget(self.search)
        row = QHBoxLayout()
        self.projects = QListWidget()
        self.projects.setMaximumWidth(280)
        self.projects.currentRowChanged.connect(self._select)
        row.addWidget(self.projects)
        editor = QTabWidget()
        project_panel, presentation_panel, mods_panel = QWidget(), QWidget(), QWidget()
        form = QFormLayout(project_panel)
        presentation_form = QFormLayout(presentation_panel)
        mods_form = QFormLayout(mods_panel)
        editor.addTab(project_panel, "Проект и релиз")
        editor.addTab(presentation_panel, "Презентация")
        editor.addTab(mods_panel, "Состав пакета")
        self.editor = editor
        self.review_panel = QWidget()
        review_layout = QVBoxLayout(self.review_panel)
        review_layout.addWidget(QLabel("REVIEWER INBOX · imported packages are untrusted"))
        self.review_list = QListWidget()
        review_layout.addWidget(self.review_list)
        review_actions = QHBoxLayout()
        for label, decision in (("Открыть .nexus-submission", "import"), ("Request Changes", "request_changes"),
                                ("Approve Candidate", "approve"), ("Reject", "reject")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, action=decision: self._review_action(action))
            review_actions.addWidget(button)
        review_layout.addLayout(review_actions)
        self.review_tab_index = editor.addTab(self.review_panel, "Review")
        editor.setTabVisible(self.review_tab_index, False)
        self.name = QLineEdit()
        self.kind = QComboBox()
        self.kind.addItems(["modpack", "server", "world"])
        self.version = QLineEdit()
        self.version.setToolTip("Версия вашего проекта, например 1.4.2. Это не версия Minecraft.")
        self.channel = QComboBox()
        self.channel.addItems(["dev", "beta", "stable"])
        self.channel.currentTextChanged.connect(self._dirty)
        form.addRow("Канал локального релиза", self.channel)
        self.metadata_fields = {}
        for key, label in (("short_name", "Короткое имя"), ("summary", "Краткое описание"),
                           ("category", "Категория"), ("tags", "Теги через запятую"), ("language", "Язык"),
                           ("visibility", "Видимость: private/unlisted/public"), ("website", "Website HTTPS"),
                           ("discord", "Discord HTTPS"), ("telegram", "Telegram HTTPS"), ("support", "Support HTTPS"),
                           ("accent", "Акцент #RRGGBB"), ("max_players", "Максимум игроков"),
                           ("status_endpoint", "Status endpoint (метаданные)")):
            control = QLineEdit()
            control.textChanged.connect(self._dirty)
            self.metadata_fields[key] = control
            presentation_form.addRow(label, control)
        self.description = QPlainTextEdit()
        self.changelog = QPlainTextEdit()
        self.description.setMaximumHeight(90)
        self.changelog.setMaximumHeight(90)
        for label, control in (("Название", self.name), ("Тип", self.kind), ("Версия", self.version),
                               ("Описание", self.description), ("Изменения", self.changelog)):
            form.addRow(label, control)
            signal = control.currentTextChanged if isinstance(control, QComboBox) else control.textChanged
            signal.connect(self._dirty)
        self.mod = QComboBox()
        self.mod_list = QListWidget()
        self.mod_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.mod_list.currentTextChanged.connect(self._mod_selected)
        self.side = QComboBox()
        self.side.addItems(sorted(SIDES))
        self.side.setToolTip("Client — только клиент; Server — только сервер; Both — обе стороны; Optional Client — необязательный клиентский мод.")
        self.mod.currentTextChanged.connect(self._mod_selected)
        self.side.currentTextChanged.connect(self._side_changed)
        mods_form.addRow("Моды", self.mod_list)
        mods_form.addRow("Сторона (вручную)", self.side)
        bulk = QHBoxLayout()
        for side, label in (("client", "Client"), ("server", "Server"), ("both", "Both"), ("optional-client", "Optional Client")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, value=side: self._bulk_classify(value))
            bulk.addWidget(button)
        mods_form.addRow("Выбранные отметить как", bulk)
        detect = QPushButton("Определить очевидные стороны автоматически")
        detect.clicked.connect(self._auto_classify)
        mods_form.addRow(detect)
        mods_form.addRow(QLabel("unknown — укажите сторону перед серверным экспортом.\nclient / optional-client — только клиент; server — сервер; both — обе стороны."))
        self.assets = {}
        for key, label in (("icon", "Иконка"), ("banner", "Баннер"), ("poster", "Постер"), ("video", "Видео")):
            field = QLineEdit()
            field.textChanged.connect(self._dirty)
            self.assets[key] = field
            asset_row = QHBoxLayout()
            asset_row.addWidget(field)
            browse = QPushButton("Выбрать…")
            browse.clicked.connect(lambda _=False, k=key: self.choose_asset(k))
            asset_row.addWidget(browse)
            presentation_form.addRow(label, asset_row)
        preview = QPushButton("Предпросмотр страницы мира")
        preview.clicked.connect(self.preview)
        presentation_form.addRow(preview)
        row.addWidget(editor, 1)
        root.addLayout(row)
        actions = QGridLayout()
        for label, callback in (("Сохранить", self.save), ("Проверить", self.validate),
                                ("Изменения файлов", self.diff), ("Тестовый запуск", self.launch),
                                ("Результат запуска", self.launch_result),
                                ("Открыть latest.log", self.open_test_log),
                                ("Скопировать результат", lambda: QApplication.clipboard().setText(self.output.toPlainText())),
                                ("Файлы проекта…", self.files_menu),
                                ("Создать локальный релиз", self.build_release),
                                ("Подготовить к публикации…", self.prepare_submission),
                                ("Client ZIP", lambda: self.export(False)),
                                ("Server ZIP", lambda: self.export(True))):
            button = QPushButton(label)
            button.clicked.connect(callback)
            index = actions.count()
            actions.addWidget(button, index // 4, index % 4)
        root.addLayout(actions)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        root.addWidget(self.output)

    def open_creator(self, academy=False):
        if self.dirty and self.identifier and not self.may_leave():
            return
        if self.creator_workspace is None:
            from nexus_launcher.nexus_platform.learning.studio import CreatorWorkspace
            owner = getattr(self.window(), "services", self.window())
            self.creator_workspace = CreatorWorkspace(self.service.instances.root.parent / ".nexus-academy", self,
                                                      reduced_motion=bool(getattr(owner, "config", {}).get("reducedMotion", False)))
            self.creator_workspace.back_requested.connect(lambda: self.stack.setCurrentIndex(0))
            self.stack.addWidget(self.creator_workspace)
        self.stack.setCurrentWidget(self.creator_workspace)
        if academy:
            self.creator_workspace.open_academy()

    def shutdown_learning(self):
        if self.creator_workspace is not None:
            self.creator_workspace.shutdown()

    def create_project(self):
        from nexus_launcher.instance_ui import CreateInstanceDialog
        dialog = CreateInstanceDialog(self)
        if dialog.exec():
            try:
                self.service.capabilities.require_creator()
                instance = self.service.instances.create(*dialog.values())
                dialog.apply_options(instance)
                self.service.instances.save(instance)
                self.refresh()
            except Exception as error:
                self.output.setPlainText(str(error))

    def choose_asset(self, key):
        filters = "Видео (*.mp4 *.webm)" if key == "video" else "Изображения (*.png *.jpg *.jpeg *.webp)"
        filename, _ = QFileDialog.getOpenFileName(self, "Ресурс презентации", "", filters)
        if filename:
            self.assets[key].setText(filename)

    def preview(self):
        if not self.save():
            return
        try:
            from nexus_launcher.nexus_platform.models import WorldView, WorldPresentation, WorldTheme
            from nexus_launcher.nexus_platform.pages import WorldPage
            from nexus_launcher.projects import ServerProfile
            assets = self.project.get("presentation", {})
            errors = self.service.validate(self.identifier)
            if errors:
                raise ValueError("\n".join(errors))
            presentation = WorldPresentation(type="video" if assets.get("video") else "image",
                image=assets.get("banner") or assets.get("poster", ""),
                poster=assets.get("poster", ""), video=assets.get("video", "")).validate()
            instance = self.service.instances.load(self.identifier)
            server = ServerProfile(instance.id, self.project["name"], "", minecraft_version=instance.minecraft_version,
                                   loader=instance.loader, loader_version=instance.loader_version)
            metadata = self.project.get("metadata", {})
            view = WorldView(server, self.project["name"], metadata.get("short_name") or self.project["name"][:2], "LOCAL DRAFT",
                             self.project.get("description", ""), metadata.get("category") or self.project["kind"], presentation,
                             WorldTheme(accent=metadata.get("accent") or "#4aa8ff").validate())
            holder = QWidget()
            layout = QVBoxLayout(holder)
            back = QPushButton("← Вернуться в редактор")
            layout.addWidget(back)
            page = WorldPage()
            self.preview_page = page
            layout.addWidget(page)
            page.set_world(view, True, True)
            page.play.setEnabled(False)
            def close_preview():
                page.release()
                self.preview_page = None
                self.stack.setCurrentIndex(0)
                self.stack.removeWidget(holder)
                holder.deleteLater()
            back.clicked.connect(close_preview)
            self.stack.addWidget(holder)
            self.stack.setCurrentWidget(holder)
        except Exception as error:
            self.output.setPlainText(str(error))

    def set_mode(self, creator):
        self.service.capabilities = Capabilities("creator" if creator else "player")
        self.editor.setTabVisible(self.review_tab_index, self.service.capabilities.can_review_submission)

    def set_role(self, role, authenticated_authority=False):
        """Only authenticated host code may supply reviewer/admin roles."""
        if role not in {"player", "creator", "reviewer", "nexus_launcher.admin"}:
            raise ValueError("Unknown Studio role")
        self.service.capabilities = Capabilities(role, bool(authenticated_authority))
        self.editor.setTabVisible(self.review_tab_index, self.service.capabilities.can_review_submission)
        if self.service.capabilities.can_review_submission:
            self._refresh_reviews()

    def _refresh_reviews(self):
        self.review_list.clear()
        for submission in self.submissions.list():
            self.review_list.addItem(f"{submission.metadata.get('title', submission.project_id)} · r{submission.revision} · {submission.status.value}")
            self.review_list.item(self.review_list.count() - 1).setData(Qt.UserRole, submission.id)

    def _review_action(self, action):
        try:
            publishing = PublishingService(self.service, self.submissions, self.service.capabilities, "local-reviewer")
            if action == "import":
                path, _ = QFileDialog.getOpenFileName(self, "Review Submission", "", "Nexus Submission (*.nexus-submission)")
                if not path: return
                submission, warnings = publishing.import_for_review(Path(path))
                self.output.setPlainText(f"{submission.metadata['title']} · revision {submission.revision}\n"
                                         f"Minecraft {submission.minecraft_version} · {submission.loader}\n"
                                         f"Validation: {len(submission.validation_result)} records\n"
                                         f"Warnings: {len(warnings)}\nClient: {submission.manifest_summary.get('downloadSize', 0) / 1048576:.1f} MB")
            else:
                item = self.review_list.currentItem()
                if not item: return
                comment = "Local reviewer decision"
                publishing.decide(item.data(Qt.UserRole), action, comment)
            self._refresh_reviews()
        except Exception as error:
            self.output.setPlainText(str(error))

    def refresh(self):
        self.service.capabilities.require_creator()
        self.projects.blockSignals(True)
        self.projects.clear()
        for instance in self.service.instances.list():
            self.projects.addItem(instance.name)
            self.projects.item(self.projects.count() - 1).setData(Qt.UserRole, instance.id)
        self.projects.blockSignals(False)
        self.projects.setCurrentRow(0)
        self._filter(self.search.text())

    def _filter(self, text):
        for index in range(self.projects.count()):
            item = self.projects.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())

    def _dirty(self, *_):
        self.dirty = True
        self.dirty_label.setText("● Несохранённые изменения")

    def may_leave(self):
        if self.creator_workspace is not None:
            self.creator_workspace.engine.exit()
        if self.preview_page:
            self.preview_page.release()
        if not self.dirty or not self.identifier:
            return True
        answer = QMessageBox.question(self, "Несохранённые изменения", "Сохранить изменения проекта?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Cancel:
            return False
        if answer == QMessageBox.Save:
            return self.save()
        self.dirty = False
        return True

    def _select(self, index):
        item = self.projects.item(index)
        if not item:
            return
        if not self.may_leave():
            self.projects.blockSignals(True)
            for i in range(self.projects.count()):
                if self.projects.item(i).data(Qt.UserRole) == self.identifier:
                    self.projects.setCurrentRow(i)
            self.projects.blockSignals(False)
            return
        try:
            self.identifier = item.data(Qt.UserRole)
            self.project = self.service.load(self.identifier)
            statistics = self.service.statistics(self.identifier)
            instance = self.service.instances.load(self.identifier)
            self.stats.setText(f"Minecraft {instance.minecraft_version} · {instance.loader} · {statistics['mods']} модов · "
                f"{statistics['files']} файлов · {statistics['bytes'] / 1048576:.1f} МБ исходных файлов · "
                f"Сторона не указана: {statistics['sides']['unknown']}")
            self.name.setText(self.project["name"])
            self.kind.setCurrentText(self.project["kind"])
            self.version.setText(self.project["version"])
            self.channel.setCurrentText(self.project.get("channel", "dev"))
            for key, field in self.metadata_fields.items():
                field.setText(self.project.get("metadata", {}).get(key, ""))
            for key, field in self.assets.items():
                field.setText(self.project.get("presentation", {}).get(key, ""))
            self.description.setPlainText(self.project.get("description", ""))
            self.changelog.setPlainText(self.project.get("changelog", ""))
            self.mod.blockSignals(True)
            self.mod.clear()
            self.mod.addItems([m.filename for m in self.service.instances.load(self.identifier).installed_mods])
            self.mod.blockSignals(False)
            self.mod_list.blockSignals(True)
            self.mod_list.clear()
            self.mod_list.addItems([m.filename for m in self.service.instances.load(self.identifier).installed_mods])
            self.mod_list.blockSignals(False)
            if self.mod_list.count(): self.mod_list.setCurrentRow(0)
            self._mod_selected(self.mod.currentText())
            self.dirty = False
            latest = next((x for x in self.submissions.list() if x.project_id == self.identifier), None)
            status = latest.status.value.replace("_", " ").title() if latest else "Local Draft"
            self.dirty_label.setText("Публикация · " + status)
            self.output.setPlainText("Локальный черновик · " + str(self.service.instances.path_for(self.identifier)))
        except Exception as error:
            self.output.setPlainText(str(error))

    def _mod_selected(self, filename):
        self.side.blockSignals(True)
        self.side.setCurrentText(self.project.get("mod_sides", {}).get(filename, "unknown"))
        self.side.blockSignals(False)

    def _side_changed(self, side):
        filename = self.mod_list.currentItem().text() if self.mod_list.currentItem() else self.mod.currentText()
        if filename:
            self.project.setdefault("mod_sides", {})[filename] = side
            self.dirty = True
            self.dirty_label.setText("● Несохранённые изменения")

    def _bulk_classify(self, side):
        files = [item.text() for item in self.mod_list.selectedItems()]
        if files and self.identifier:
            try:
                self.service.classify(self.identifier, files, side)
                self.project = self.service.load(self.identifier)
                self._mod_selected(self.mod_list.currentItem().text() if self.mod_list.currentItem() else "")
                self.output.setPlainText(f"{len(files)} модов отмечено как {side}.")
            except Exception as error: self.output.setPlainText(str(error))

    def _auto_classify(self):
        if self.identifier:
            before = dict(self.project.get("mod_sides", {}))
            self._start_operation(lambda: self._auto_classify_worker(before))

    def _auto_classify_worker(self, before):
        after = self.service.auto_classify(self.identifier)
        return f"Автоматически определено: {sum(before.get(k, 'unknown') == 'unknown' and v != 'unknown' for k, v in after.items())}. Неопределённые моды оставлены для ручной проверки."

    def save(self):
        if not self.identifier:
            return False
        try:
            self.project.update(name=self.name.text(), kind=self.kind.currentText(), version=self.version.text(),
                                channel=self.channel.currentText(), description=self.description.toPlainText(),
                                changelog=self.changelog.toPlainText(), presentation={k: v.text().strip() for k, v in self.assets.items()},
                                metadata={k: v.text().strip() for k, v in self.metadata_fields.items()})
            self.service.save(self.identifier, self.project)
            self.dirty = False
            self.dirty_label.setText("Локальный черновик")
            self.output.setPlainText("Черновик сохранён локально.")
            return True
        except Exception as error:
            self.output.setPlainText(str(error))
            return False

    def validate(self):
        if self.save():
            server = self.kind.currentText() == "server"
            self._start_operation(lambda: self._validation_worker(server))

    def _validation_worker(self, server):
        report = self.service.validation_report(self.identifier, server)
        return "\n".join(f"{item.level} · {item.message}" + (f"\n  → {item.action}" if item.action else "") for item in report)

    def diff(self):
        if self.identifier:
            self._start_operation(self._diff_worker)

    def _diff_worker(self):
        changes = self.service.changes(self.identifier)
        return "\n".join(k + ":\n" + "\n".join(v) for k, v in changes.items())

    def launch(self):
        if self.save():
            self.test_launch_requested.emit(self.identifier)

    def launch_result(self):
        if not self.identifier:
            return
        instance = self.service.instances.load(self.identifier)
        root = self.service.instances.path_for(self.identifier)
        self.output.setPlainText(f"TEST RESULT\nЗапуск: {instance.last_test_launch or 'не запускалась'}\n"
            f"Exit code: {instance.last_test_exit_code if instance.last_test_exit_code is not None else 'пока нет'}\n"
            f"Длительность: {instance.last_test_duration if instance.last_test_duration is not None else 'пока нет'} с\n"
            f"Лог: {root / 'logs/latest.log'}\nОтчёты: {root / 'crash-reports'}")

    def open_test_log(self):
        if not self.identifier: return
        path = self.service.instances.path_for(self.identifier) / "logs/latest.log"
        if path.is_file(): open_in_file_manager(Path(path))
        else: self.output.setPlainText("latest.log ещё не создан.")

    def files_menu(self):
        if not self.identifier:
            return
        from nexus_launcher.safe_paths import checked_path
        menu = QMenu(self)
        for relative in ("mods", "config", "resourcepacks", "shaderpacks", "kubejs", "datapacks", "screenshots", "logs", "crash-reports", ".nexus/backups"):
            def open_folder(_=False, name=relative):
                try:
                    path = checked_path(self.service.instances.path_for(self.identifier), name)
                    path.mkdir(parents=True, exist_ok=True)
                    open_in_file_manager(Path(path))
                except Exception as error:
                    self.output.setPlainText(str(error))
            menu.addAction(relative, open_folder)
        menu.exec(self.mapToGlobal(self.rect().center()))

    def export(self, server):
        if not self.save():
            return
        try:
            summary = self.service.export_summary(self.identifier, server)
            review = (f"{'SERVER' if server else 'CLIENT'} PACK\n\nIncluded mods: {summary.included_mods}\n"
                f"Configs: {summary.configs}\nDatapacks: {summary.datapacks}\nExcluded mods: {summary.excluded_mods}\n"
                f"Excluded shaders: {summary.excluded_shaders}\nUnknown: {summary.unknown_mods}\nSource size: {summary.total_bytes / 1048576:.1f} МБ")
            if summary.unknown_mods:
                QMessageBox.warning(self, "Экспорт заблокирован", review + "\n\nУкажите сторону неизвестных модов.")
                return
            if QMessageBox.question(self, "Проверка пакета", review + "\n\nСоздать архив?") != QMessageBox.Yes:
                return
        except Exception as error:
            self.output.setPlainText(str(error)); return
        path, _ = QFileDialog.getSaveFileName(self, "Локальный пакет", "server.zip" if server else "client.zip", "ZIP (*.zip)")
        if path:
            self._start_operation(lambda: self._export_worker(Path(path), server))

    def _export_worker(self, path, server):
        self.service.export(self.identifier, path, server)
        project = self.service.load(self.identifier)
        project["baseline"] = self.service.inventory(self.identifier)
        self.service.save(self.identifier, project)
        return "Пакет сохранён: " + str(path) + "\nЛокальный кандидат без официальной подписи."

    def _start_operation(self, worker):
        if self.busy: return
        self.busy = True
        self.output.setPlainText("Операция выполняется по реальным файлам…")
        def run():
            try: self.operation_done.emit(worker())
            except Exception as error: self.operation_failed.emit(str(error))
        threading.Thread(target=run, daemon=True).start()

    def _operation_done(self, message):
        self.busy = False
        if self.identifier:
            try: self.project = self.service.load(self.identifier)
            except Exception: pass
        self.output.setPlainText(message)

    def _operation_failed(self, message):
        self.busy = False
        self.output.setPlainText(message)

    def build_release(self):
        if not self.save():
            return
        try:
            changes = self.service.changes(self.identifier)
            review = f"Версия: {self.project['version']}\nКанал: {self.project['channel']}\nЛокальный кандидат без официальной подписи.\n" + "\n".join(k + ": " + str(len(v)) for k, v in changes.items())
            if QMessageBox.question(self, "Проверка перед сборкой", review) == QMessageBox.Yes:
                self.export(self.project["kind"] == "server")
        except Exception as error:
            self.output.setPlainText(str(error))

    def prepare_submission(self):
        if not self.save():
            return
        try:
            report = self.service.validation_report(self.identifier, False)
            errors = [item for item in report if item.level == "ERROR"]
            warnings = [item for item in report if item.level == "WARNING"]
            if errors:
                raise ValueError("Исправьте ошибки перед подготовкой:\n" + "\n".join("• " + x.message for x in errors))
            summary = ("ПОДГОТОВКА К ПУБЛИКАЦИИ\n\n"
                       "1. Информация — заполнена\n2. Презентация — использует текущий редактор\n"
                       "3. Контент — будет собран в Client Artifact\n4. Сервер — optional\n"
                       "5. Проверка — без ошибок\n6. Релиз — unsigned local candidate\n"
                       "7. Предпросмотр — доступен через реальную World Page\n8. Отправка — экспорт локального package\n\n"
                       f"Warnings: {len(warnings)}\nПакет никуда не отправляется.")
            if QMessageBox.question(self, "Submission Wizard", summary + "\n\nПродолжить?") != QMessageBox.Yes:
                return
            destination, _ = QFileDialog.getSaveFileName(self, "Локальный submission package",
                                                         f"{self.project['name']}-{self.project['version']}.nexus-submission",
                                                         "Nexus Submission (*.nexus-submission)")
            if not destination:
                return
            self._start_operation(lambda: self._prepare_submission_worker(Path(destination), bool(warnings)))
        except Exception as error:
            self.output.setPlainText(str(error))

    def _prepare_submission_worker(self, destination, warnings_confirmed):
        service = PublishingService(self.service, self.submissions, self.service.capabilities)
        submission = service.prepare(self.identifier, destination, warnings_confirmed=warnings_confirmed)
        return (f"Submission package prepared\nID: {submission.id}\nRevision: {submission.revision}\n"
                f"Status: {submission.status.value}\n{destination}\n\nДанные никуда не отправлены.")
