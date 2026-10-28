"""Workspace-sized Modrinth catalogue with bounded, stale-safe requests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from PySide6.QtCore import QObject, Signal, Slot, Qt, QTimer, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget, QTabWidget, QScrollArea, QProgressBar,
)

from .catalog_provider import CatalogProvider
from .catalog_filters import ModrinthFilterState, SORTS
from .catalog_filter_panel import FilterPanel, CatalogComboBox
from .catalog_controls import NexusButton, FlowLayout
from .artwork import landscape
from .mod_profile import ModRow, ProjectBody
from .content_state import ContentState
from .mod_media import CACHE, safe_image, fetch_media, decode_image, GalleryImage


class CatalogBridge(QObject):
    tags = Signal(object, str)
    ready = Signal(int, object, str)
    icon = Signal(int, str, bytes)
    project = Signal(int, object, str)
    media = Signal(int, int, bytes)
    profile_icon = Signal(int, bytes)


class ModCatalog(QWidget):
    back_requested = Signal()
    install_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Segoe UI", 10))
        self.provider = CatalogProvider()
        self.instance = None
        self.filter_state = ModrinthFilterState()
        self._instance_searches = {}
        self.filter_panel = None
        self._tags = {}
        self._tags_future = None
        self.tags_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='modrinth-tags')
        self.generation = 0
        self.offset = 0
        self.total = 0
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="modrinth-catalog")
        self.pending = None
        self.bridge = CatalogBridge(self)
        self.bridge.ready.connect(self._received, Qt.ConnectionType.QueuedConnection)
        self.bridge.tags.connect(self._tags_received, Qt.ConnectionType.QueuedConnection)
        self.bridge.icon.connect(self._icon_received, Qt.ConnectionType.QueuedConnection)
        self.bridge.project.connect(self._project_received, Qt.ConnectionType.QueuedConnection)
        self.bridge.media.connect(self._gallery_received, Qt.ConnectionType.QueuedConnection)
        self.bridge.profile_icon.connect(self._profile_icon_received, Qt.ConnectionType.QueuedConnection)
        self.media_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='modrinth-icons')
        self.icon_cache = CACHE
        self._icon_futures = []
        self._project_media_futures = []
        self.detail_generation = 0
        self.deadline = QTimer(self)
        self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.detail_deadline = QTimer(self)
        self.detail_deadline.setSingleShot(True)
        self.detail_deadline.timeout.connect(self._detail_timeout)
        self.install_busy = False
        self.project_hit = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        header = QFrame()
        header.setObjectName("modSearchHeader")
        head = QVBoxLayout(header)
        nav = QHBoxLayout()
        back = NexusButton("Назад к сборке")
        back.clicked.connect(self.back_requested)
        nav.addWidget(back)
        self.destination = QLabel()
        self.destination.setWordWrap(True)
        nav.addWidget(self.destination, 1)
        head.addLayout(nav)
        search_row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("Поиск модов на Modrinth")
        self.query.setAccessibleName("Поиск модов")
        self.query.setClearButtonEnabled(True)
        self.query.returnPressed.connect(self.search)
        # Explicit submit avoids firing requests while typing/composing IME text.
        self.query.textChanged.connect(self._query_changed)
        search = NexusButton("Найти", variant="primary")
        search.clicked.connect(self.search)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(search)
        head.addLayout(search_row)
        filter_row = QHBoxLayout()
        self.filters_button = NexusButton('Фильтры')
        self.filters_button.setAccessibleName('Открыть фильтры Modrinth')
        self.filters_button.clicked.connect(self._open_filters)
        filter_row.addWidget(self.filters_button)
        self.status = QLabel('Выберите сборку')
        self.status.setWordWrap(True)
        head.addWidget(self.status)
        filter_row.addStretch(1)
        filter_row.addWidget(QLabel('Сортировка'))
        self.sort = self._combo('Сортировка', [(label, value) for value, label in SORTS.items()])
        self.sort.currentIndexChanged.connect(self._sort_changed)
        filter_row.addWidget(self.sort)
        head.addLayout(filter_row)
        self.chips_widget = QWidget()
        self.chips = FlowLayout(self.chips_widget)
        self.chips_scroll = self.chips_widget
        self.chips_widget.setAccessibleName('Активные фильтры Modrinth')
        self.chips_widget.hide()
        head.addWidget(self.chips_widget)
        self.search_header = header
        root.addWidget(header)
        self.results = QListWidget()
        self.results.setWordWrap(True)
        self.results.setAccessibleName("Результаты Modrinth")
        # The embedded ModRow owns the visible icon. Keep the item's QIcon for
        # opening its profile without painting a second copy beside the row.
        self.results.setIconSize(QSize(0, 0))
        self.results.itemActivated.connect(self._open_project)
        self.results.itemClicked.connect(self._open_project)
        self.results.currentRowChanged.connect(self._selection_changed)
        self.results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        root.addWidget(self.results, 1)
        self.catalog_state = ContentState("Найди свой мод.", "Название, категория и версия помогут выбрать дополнение.", "Найти", self.search, "modrinth")
        self.catalog_loading = QProgressBar()
        self.catalog_loading.setRange(0, 0)
        self.catalog_loading.setTextVisible(False)
        self.catalog_loading.setAccessibleName("Загрузка каталога Modrinth")
        state_layout = self.catalog_state.layout()
        if isinstance(state_layout, QVBoxLayout):
            state_layout.insertWidget(0, self.catalog_loading)
        self.catalog_loading.hide()
        root.addWidget(self.catalog_state, 1)
        self.profile_page = QWidget()
        profile_layout = QVBoxLayout(self.profile_page)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        self.return_results = QPushButton('← Назад к результатам')
        self.return_results.clicked.connect(self._close_project)
        profile_layout.addWidget(self.return_results, 0, Qt.AlignmentFlag.AlignLeft)
        profile_header = QFrame()
        profile_header.setObjectName('modProfileHeader')
        identity = QHBoxLayout(profile_header)
        self.profile_icon = QLabel()
        self.profile_icon.setObjectName('modIcon')
        self.profile_icon.setFixedSize(88, 88)
        self.profile_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        identity.addWidget(self.profile_icon)
        titles = QVBoxLayout()
        self.project_title = QLabel()
        self.project_title.setObjectName('modProjectTitle')
        self.project_title.setTextFormat(Qt.TextFormat.PlainText)
        self.project_title.setWordWrap(True)
        self.project_summary = QLabel()
        self.project_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.project_summary.setObjectName('muted')
        self.project_summary.setWordWrap(True)
        self.project_author = QLabel()
        self.project_author.setObjectName('muted')
        self.project_author.setTextFormat(Qt.TextFormat.PlainText)
        self.project_metadata = QLabel()
        self.project_metadata.setTextFormat(Qt.TextFormat.PlainText)
        self.project_metadata.setObjectName('modMetadata')
        self.project_metadata.setWordWrap(True)
        titles.addWidget(self.project_title)
        titles.addWidget(self.project_author)
        titles.addWidget(self.project_summary)
        titles.addWidget(self.project_metadata)
        identity.addLayout(titles, 1)
        self.profile_install = QPushButton('Установить')
        self.profile_install.setObjectName('primaryAction')
        self.profile_install.clicked.connect(self._install_selected)
        identity.addWidget(self.profile_install, 0, Qt.AlignmentFlag.AlignTop)
        profile_layout.addWidget(profile_header)
        self.project_tabs = QTabWidget()
        self.detail = ProjectBody()
        self.detail.setOpenLinks(False)
        self.detail.setAccessibleName('Профиль мода')
        self.project_tabs.addTab(self.detail, 'Обзор')
        self.changelog = ProjectBody()
        self.project_tabs.addTab(self.changelog, 'Изменения')
        self.gallery = QScrollArea()
        self.gallery.setWidgetResizable(True)
        self.gallery_content = QWidget()
        self.gallery_layout = QVBoxLayout(self.gallery_content)
        self.gallery.setWidget(self.gallery_content)
        self.gallery_labels = []
        self.project_tabs.addTab(self.gallery, 'Галерея')
        self.versions = ProjectBody()
        self.project_tabs.addTab(self.versions, 'Версии')
        profile_layout.addWidget(self.project_tabs, 1)
        self.profile_page.hide()
        root.addWidget(self.profile_page, 1)
        footer = QHBoxLayout()
        self.previous = QPushButton("Предыдущие")
        self.previous.clicked.connect(lambda: self.search(offset=max(0, self.offset - 20)))
        self.next = QPushButton("Следующие")
        self.next.clicked.connect(lambda: self.search(offset=self.offset + 20))
        self.install = QPushButton("Установить выбранный мод")
        self.install.setMinimumWidth(240)
        self.install.clicked.connect(self._install_selected)
        footer.addWidget(self.previous)
        footer.addWidget(self.next)
        footer.addStretch()
        footer.addWidget(self.install)
        root.addLayout(footer)
        from .presentation_style import stylesheet
        self.setStyleSheet(stylesheet())
        self._invalidate()

    @staticmethod
    def _combo(label, values):
        combo = CatalogComboBox()
        # Painted catalogue control with an in-window popover.
        combo.setAccessibleName(label)
        combo.setToolTip(label)
        for text, value in values:
            combo.addItem(text, value)
        return combo

    def open_for(self, instance):
        if self.instance:
            self._instance_searches[self.instance.id] = (self.filter_state, self.query.text(), self.offset)
        self.instance = instance
        state, query, offset = self._instance_searches.get(instance.id, (ModrinthFilterState.for_instance(instance), '', 0))
        self.filter_state = state
        self.query.blockSignals(True)
        self.query.setText(query)
        self.query.blockSignals(False)
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(self.sort.findData(state.index))
        self.sort.blockSignals(False)
        self._update_chips()
        self.destination.setText(
            f"Сборка: {instance.name} · Minecraft {instance.minecraft_version} · {instance.loader.title()}"
        )
        self.search(offset=offset)

    def _update_chips(self):
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item is not None and item.widget():
                item.widget().deleteLater()
        active = self.filter_state.chips()
        self.filters_button.setText(f'Фильтры {len(active)}' if active else 'Фильтры')
        for field, value, label in active:
            chip = NexusButton(label + ' ×', variant='chip')
            chip.setAccessibleName('Убрать фильтр: ' + label)
            chip.setToolTip('Убрать фильтр: ' + label)
            chip.clicked.connect(lambda _=False, f=field, v=value: self._remove_filter(f, v))
            self.chips.addWidget(chip)
        reset = NexusButton('Сбросить всё', variant='quiet')
        reset.clicked.connect(self._reset_filters)
        self.chips.addWidget(reset)
        self.chips_widget.setVisible(bool(active))

    def _remove_filter(self, field, value):
        self._apply_filters(self.filter_state.remove(field, value))

    def _reset_filters(self):
        if self.instance:
            self._apply_filters(ModrinthFilterState.for_instance(self.instance))

    def _sort_changed(self, *_):
        self._apply_filters(replace(self.filter_state, index=self.sort.currentData()))

    def _query_changed(self, *_):
        self.offset = 0
        self._invalidate()

    def _apply_filters(self, state):
        self.filter_state = state
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(self.sort.findData(state.index))
        self.sort.blockSignals(False)
        self._update_chips()
        self.search()

    def _open_filters(self):
        if not self.instance:
            return
        if self.filter_panel:
            self.filter_panel.raise_()
            return
        panel = FilterPanel(self.filter_state, ModrinthFilterState.for_instance(self.instance), self)
        self.filter_panel = panel
        panel.accepted.connect(lambda: self._apply_filters(panel.state()))
        panel.finished.connect(lambda _result: self._filter_closed(panel))
        panel.retry.clicked.connect(self._load_tags)
        if self._tags:
            panel.set_metadata(self._tags)
        else:
            self._load_tags()
        panel.open()

    def _filter_closed(self, panel):
        self.filter_panel = None
        panel.deleteLater()

    def _load_tags(self):
        if self._tags_future and not self._tags_future.done():
            return
        if self.filter_panel:
            self.filter_panel.metadata_status.setText('Загрузка списков Modrinth…')
            self.filter_panel.retry.hide()
        def work():
            try:
                tags, error = self.provider.filter_tags(), ''
            except Exception as exc:
                tags, error = {}, str(exc)
            try:
                self.bridge.tags.emit(tags, error)
            except RuntimeError:
                pass
        self._tags_future = self.tags_pool.submit(work)

    @Slot(object, str)
    def _tags_received(self, tags, error):
        if not error:
            self._tags = tags
        if self.filter_panel:
            self.filter_panel.set_metadata(tags, error)

    def _invalidate(self, *_):
        for future in self._icon_futures:
            future.cancel()
        self._icon_futures.clear()
        self.deadline.stop()
        self._close_project()
        self.generation += 1
        if self.pending:
            self.pending.cancel()
        self.results.clear()
        self._catalog_feedback("Найди свой мод.", "Введи название или выбери категорию, затем нажми «Найти».", "Найти")
        self.previous.setEnabled(False)
        self.next.setEnabled(False)
        self.install.setEnabled(False)
        self.status.setText("Нажмите «Найти», чтобы применить поиск.")

    def search(self, *_args, offset=0):
        if not self.instance:
            return
        self._invalidate()
        self.offset = offset
        token = self.generation
        query = self.query.text().strip()
        state = self.filter_state
        self.status.setText("Загрузка Modrinth…")
        self._catalog_feedback("Открываем Modrinth…", "Ищем дополнения по выбранным фильтрам.", "", loading=True)
        self.deadline.start(12000)

        def work():
            try:
                payload, error = self.provider.search_page(query, filters=state, offset=offset), ""
            except Exception as exc:
                payload, error = {}, str(exc)
            try:
                self.bridge.ready.emit(token, payload, error)
            except RuntimeError:
                pass  # The application was closed while the read-only request finished.

        self.pending = self.pool.submit(work)

    @Slot(int, object, str)
    def _received(self, token, payload, error):
        if token != self.generation:
            return
        self.deadline.stop()
        self.results.clear()
        if error:
            self.status.setText("Не удалось загрузить каталог. Нажмите «Найти», чтобы повторить.")
            self.status.setToolTip(error)
            self._catalog_feedback("Каталог временно недоступен.", "Проверь подключение к интернету и повтори поиск.", "Повторить")
            return
        hits = payload.get("hits", [])
        self.catalog_state.setVisible(not hits)
        self.results.setVisible(bool(hits))
        if not hits:
            self._catalog_feedback("Совместимых модов не найдено.", "Измени запрос или сбрось фильтры. Установка остаётся привязана к выбранной сборке.", "Повторить поиск")
        self.total = int(payload.get("total_hits", len(hits)))
        sides = {"required": "обязателен", "optional": "поддерживается", "unsupported": "не поддерживается", "unknown": "не указан"}
        for hit in hits:
            row = QListWidgetItem(
                f"{hit['title']} — {hit.get('author', '')}\n{hit.get('description', '')}\n"
                f"Скачиваний: {int(hit.get('downloads', 0)):,} · Обновлён: {hit.get('date_modified', '')[:10]} · "
                f"Клиент: {sides.get(hit.get('client_side'), 'не указан')} · Сервер: {sides.get(hit.get('server_side'), 'не указан')}"
            )
            row.setData(Qt.ItemDataRole.UserRole, hit["project_id"])
            row.setData(Qt.ItemDataRole.UserRole + 1, hit)
            self.results.addItem(row)
            widget = ModRow(hit, self.instance, lambda _=False, item=row: self._open_project(item),
                            lambda _=False, item=row: self._install_row(item), context=self._hit_context(hit))
            row.setSizeHint(QSize(0, 132))
            self.results.setItemWidget(row, widget)
            url = hit.get('icon_url')
            if safe_image(url):
                cached = self.icon_cache.get(url)
                if cached is not None:
                    self._icon_received(token, hit['project_id'], cached)
                else:
                    self._icon_futures.append(self.media_pool.submit(self._fetch_icon, token, hit['project_id'], url))
        self.status.setText(
            f"{self.total:,} проектов · Показано {self.offset + 1}–{self.offset + len(hits)}".replace(",", " ")
            if hits else "Совместимых модов не найдено. Измените поиск или категорию."
        )
        self._selection_changed(self.results.currentRow())
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(self.offset + len(hits) < self.total and bool(hits))

    def _timeout(self):
        self.generation += 1
        if self.pending:
            self.pending.cancel()
        self.status.setText('Modrinth не ответил за 12 секунд. Проверьте соединение и нажмите «Найти».')
        self._catalog_feedback("Modrinth не ответил.", "Проверь соединение или попробуй поиск ещё раз.", "Повторить")

    def _catalog_feedback(self, title, description, action, loading=False):
        self.catalog_state.title.setText(title)
        self.catalog_state.description.setText(description)
        self.catalog_state.action.setText(action)
        self.catalog_state.action.setVisible(bool(action))
        self.catalog_loading.setVisible(loading)
        self.catalog_state.show()
        self.results.hide()

    def _fetch_icon(self, token, project_id, url):
        data = fetch_media(url, cancelled=lambda: token != self.generation, max_bytes=1024 * 1024)
        try:
            self.bridge.icon.emit(token, project_id, data)
        except RuntimeError:
            pass

    @Slot(int, str, bytes)
    def _icon_received(self, token, project_id, data):
        if token != self.generation or len(data) > 1024 * 1024:
            return
        image = decode_image(data, width=88, dimension=2048)
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        for index in range(self.results.count()):
            row = self.results.item(index)
            if row.data(Qt.ItemDataRole.UserRole) == project_id:
                row.setIcon(QIcon(pixmap))
                widget = self.results.itemWidget(row)
                if isinstance(widget, ModRow):
                    widget.icon.setPixmap(pixmap.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        if self.project_hit.get('project_id') == project_id and self.profile_page.isVisible():
            self.profile_icon.setPixmap(pixmap)

    def _fetch_profile_icon(self, token, url):
        data = fetch_media(url, cancelled=lambda: token != self.detail_generation, max_bytes=1024 * 1024)
        try:
            self.bridge.profile_icon.emit(token, data)
        except RuntimeError:
            pass

    @Slot(int, bytes)
    def _profile_icon_received(self, token, data):
        if token != self.detail_generation or len(data) > 1024 * 1024:
            return
        image = decode_image(data, width=88, dimension=2048)
        if not image.isNull():
            self.profile_icon.setPixmap(QPixmap.fromImage(image))

    def _open_project(self, item):
        if self.instance is None:
            return
        self.catalog_state.hide()
        self.detail_generation += 1
        token = self.detail_generation
        project_id = item.data(Qt.ItemDataRole.UserRole)
        instance = self.instance
        self.project_hit = item.data(Qt.ItemDataRole.UserRole + 1) or {}
        self.results.setCurrentItem(item)
        self.project_title.setText(item.text().split('\n')[0])
        self.project_author.setText('от ' + self.project_hit['author'] if self.project_hit.get('author') else '')
        self.project_summary.setText('Загрузка страницы мода…')
        self.project_metadata.setText(self.destination.text())
        icon = item.icon().pixmap(88, 88)
        self.profile_icon.clear()
        self.profile_icon.setPixmap(icon if not icon.isNull() else landscape(self.project_hit.get('project_id', 'mod'), 88, 88))
        self.search_header.hide()
        self.results.hide()
        self.previous.hide()
        self.next.hide()
        self.install.hide()
        self.profile_page.show()
        self.project_tabs.setCurrentIndex(0)
        self.detail.setPlainText('Загрузка профиля мода…')
        self.changelog.setPlainText('Загрузка изменений…')
        self.versions.setPlainText('Загрузка совместимых версий…')
        while self.gallery_layout.count():
            widget = self.gallery_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.gallery_labels = []
        self.gallery_layout.addWidget(QLabel('Загрузка галереи…'))
        self.detail_deadline.start(12000)
        def work():
            try:
                payload, error = self.provider.project(project_id), ''
                try:
                    payload = dict(payload)
                    payload['_compatible_versions'] = self.provider.versions(project_id, instance.minecraft_version, instance.loader)
                except Exception:
                    payload['_versions_error'] = True
            except Exception as exc:
                payload, error = {}, str(exc)
            try:
                self.bridge.project.emit(token, payload, error)
            except RuntimeError:
                pass
        self.pool.submit(work)

    @Slot(int, object, str)
    def _project_received(self, token, payload, error):
        if token != self.detail_generation:
            return
        self.detail_deadline.stop()
        if error:
            self.detail.setPlainText('Не удалось загрузить профиль. Вернитесь к результатам и откройте мод повторно.\n' + error)
            return
        self.project_title.setText(payload.get('title', ''))
        icon_url = payload.get('icon_url')
        if safe_image(icon_url):
            self._project_media_futures.append(self.media_pool.submit(self._fetch_profile_icon, token, icon_url))
        self.project_summary.setText(payload.get('description', ''))
        games = payload.get('game_versions', [])
        compact_games = ', '.join(games[-6:]) + (f' · ещё {len(games) - 6}' if len(games) > 6 else '')
        self.project_metadata.setText('Minecraft: ' + compact_games +
            ' · ' + ', '.join(payload.get('loaders', [])) + ' · ' + (payload.get('license') or {}).get('name', ''))
        self.project_metadata.setToolTip('Minecraft: ' + ', '.join(games))
        self.detail.setMarkdown(payload.get('body') or 'Описание пока не опубликовано.')
        self.detail.verticalScrollBar().setValue(0)
        versions = payload.get('_compatible_versions', [])
        self.versions.setPlainText('\n\n'.join(
            f'{v.get("name", v.get("version_number", ""))}\n{v.get("date_published", "")[:10]} · '
            f'{", ".join(v.get("loaders", []))} · {", ".join(v.get("game_versions", []))}' for v in versions)
            or ('Не удалось загрузить версии. Откройте страницу повторно.' if payload.get('_versions_error') else 'Совместимых версий нет.'))
        self.changelog.setMarkdown((versions[0].get('changelog') if versions else '') or 'Список изменений пока недоступен.')
        while self.gallery_layout.count():
            widget = self.gallery_layout.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        self.gallery_labels = []
        gallery = sorted(payload.get('gallery', []), key=lambda media: (not media.get('featured', False), media.get('ordering') or 0))
        for index, media in enumerate(gallery[:12]):
            card = QWidget()
            box = QVBoxLayout(card)
            box.setContentsMargins(0, 0, 0, 16)
            box.setSpacing(8)
            label = GalleryImage()
            label.setAccessibleName(media.get('title') or 'Изображение проекта Modrinth')
            box.addWidget(label)
            for text in (media.get('title'), media.get('description')):
                if text:
                    caption = QLabel(text)
                    caption.setTextFormat(Qt.TextFormat.PlainText)
                    caption.setWordWrap(True)
                    caption.setObjectName('muted')
                    box.addWidget(caption)
            self.gallery_layout.addWidget(card)
            self.gallery_labels.append(label)
            self._project_media_futures.append(self.media_pool.submit(self._fetch_gallery, token, index, media.get('url', '')))
        if not self.gallery_labels:
            self.gallery_layout.addWidget(QLabel('Автор пока не добавил изображения.'))
        self.gallery_layout.addStretch()

    def _fetch_gallery(self, token, index, url):
        data = fetch_media(url, cancelled=lambda: token != self.detail_generation)
        try:
            self.bridge.media.emit(token, index, data)
        except RuntimeError:
            pass

    @Slot(int, int, bytes)
    def _gallery_received(self, token, index, data):
        if token != self.detail_generation or index >= len(self.gallery_labels):
            return
        self.gallery_labels[index].set_image(decode_image(data))

    def _close_project(self):
        self.detail_deadline.stop()
        for future in self._project_media_futures:
            future.cancel()
        self._project_media_futures.clear()
        for body in (self.detail, self.changelog, self.versions):
            body.cancel_media()
        self.detail_generation += 1
        self.profile_page.hide()
        self.search_header.show()
        self.previous.show()
        self.next.show()
        self.install.show()
        self.results.show()

    def _detail_timeout(self):
        self.detail_generation += 1
        self.detail.setPlainText('Modrinth не ответил за 12 секунд. Вернитесь к результатам и откройте мод повторно.')

    def _hit_context(self, hit):
        if not self.instance:
            return ''
        versions = hit.get('versions', [])
        shown = [value for value in self.filter_state.versions if value in versions]
        if not shown:
            shown = ([self.instance.minecraft_version] if self.instance.minecraft_version in versions
                     else versions[-3:])
        if not versions:
            shown = [self.instance.minecraft_version]
        loader_tags = set(hit.get('categories', [])) | set(hit.get('loaders', []))
        loaders = [value for value in self.filter_state.loaders if value in loader_tags]
        if not loaders:
            known = set(self._tags.get('loaders', [])) | {'fabric', 'forge', 'neoforge', 'quilt'}
            loaders = sorted(loader_tags & known)
        return 'Minecraft ' + ', '.join(shown[:3]) + (' · ' + ', '.join(value.title() for value in loaders) if loaders else '')

    def _compatible_hit(self, hit):
        if not self.instance or self.instance.loader == 'vanilla':
            return False
        if hit.get('project_type', 'mod') != 'mod':
            return False
        if hit.get('versions') and self.instance.minecraft_version not in hit['versions']:
            return False
        loaders = set(hit.get('categories', [])) | set(hit.get('loaders', []))
        known = set(self._tags.get('loaders', [])) | {'fabric', 'forge', 'neoforge', 'quilt'}
        if loaders & known and self.instance.loader not in loaders:
            return False
        return True  # The unchanged resolver verifies precise per-version compatibility.

    def _selection_changed(self, row):
        item = self.results.item(row) if row >= 0 else None
        allowed = not self.install_busy and item is not None and self._compatible_hit(item.data(Qt.ItemDataRole.UserRole + 1) or {})
        self.install.setEnabled(allowed)
        self.profile_install.setEnabled(allowed)
        for index in range(self.results.count()):
            item = self.results.item(index)
            widget = self.results.itemWidget(item)
            if isinstance(widget, ModRow):
                compatible = self._compatible_hit(item.data(Qt.ItemDataRole.UserRole + 1) or {})
                widget.install.setEnabled(not self.install_busy and compatible)
                widget.install.setToolTip('' if compatible else 'Не совместим с выбранной сборкой')
        self.install.setToolTip('' if allowed else 'Выбери мод, совместимый с версией и загрузчиком сборки')

    def _install_selected(self):
        item = self.results.currentItem()
        if item and self.instance is not None and self.install.isEnabled():
            self.install_requested.emit(self.instance.id, item.data(Qt.ItemDataRole.UserRole))

    def _install_row(self, item):
        self.results.setCurrentItem(item)
        self._install_selected()

    def leave(self):
        if self.filter_panel:
            self.filter_panel.reject()
        self.sort.hidePopup()
        self._invalidate()

    def set_install_busy(self, busy):
        self.install_busy = busy
        self.install.setText("Подготовка / установка…" if busy else "Установить выбранный мод")
        self.profile_install.setText('Установка…' if busy else 'Установить')
        self._selection_changed(self.results.currentRow())

    def shutdown(self):
        self.leave()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.media_pool.shutdown(wait=False, cancel_futures=True)
        self.tags_pool.shutdown(wait=False, cancel_futures=True)
