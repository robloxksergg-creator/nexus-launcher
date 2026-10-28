"""Integrated catalogue filter drawer with custom selectors and draft semantics."""
from PySide6.QtCore import Qt, QEvent, Signal
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QWidget, QFrame,
    QScrollArea, QListWidgetItem, QApplication,
)
from shiboken6 import isValid
from .catalog_filters import ModrinthFilterState, ENVIRONMENTS
from .catalog_controls import NexusButton, ChoicePopup, CatalogComboBox, FlowLayout, tag_label
from .theme_tokens import TOKENS as T, TYPE


class TagSelection(NexusButton):
    changed = Signal()

    def __init__(self, title, selected=(), parent=None):
        super().__init__('', parent, variant='selector', chevron=True)
        self.title = title
        self._selected = tuple(selected)
        self.setAccessibleName(title + ': выбор нескольких значений')
        self.popup = ChoicePopup(self)
        self.search = self.popup.search
        self.search.setAccessibleName('Поиск: ' + title)
        self.search.setPlaceholderText('Найти версию…' if title == 'Версия Minecraft' else 'Поиск…')
        self.list = self.popup.list
        self.list.setAccessibleName(title)
        self.list.activated_choice.connect(self._toggle)
        self.list.itemChanged.connect(self._changed)
        self.popup.clear_button.clicked.connect(self.clear)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self.popup.close_popup)
        self.clicked.connect(self.showPopup)
        self.set_values([])

    def selected(self):
        return self._selected

    def set_values(self, values):
        self.list.blockSignals(True)
        self.list.clear()
        for value in dict.fromkeys([*self._selected, *values]):
            item = QListWidgetItem(tag_label(value))
            item.setData(Qt.ItemDataRole.UserRole, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if value in self._selected else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        self.list.blockSignals(False)
        self._filter(self.search.text())
        self._summary()

    def _toggle(self, item):
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked else Qt.CheckState.Checked)

    def toggle_value(self, value):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == value:
                self._toggle(self.list.item(i))
                return

    def _changed(self, item=None):
        selected = tuple(self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                         if self.list.item(i).checkState() == Qt.CheckState.Checked)
        if len(selected) > 64 and item is not None:
            self.list.blockSignals(True)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list.blockSignals(False)
            self.setToolTip('Не более 64 значений в группе')
            return
        self._selected = selected
        self._summary()

    def _summary(self):
        labels = [tag_label(value) for value in self._selected]
        self.setText((labels[0] + (f' +{len(labels)-1}' if len(labels) > 1 else '')) if labels else 'Любые')
        self.setToolTip(', '.join(labels) or 'Любые')
        self.changed.emit()

    def _filter(self, text):
        for i in range(self.list.count()):
            item = self.list.item(i)
            item.setHidden(text.casefold() not in item.text().casefold())

    def clear(self):
        self._selected = ()
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._summary()

    def showPopup(self, _checked=False, *, anchor=None):
        if self.popup.isVisible():
            self.popup.close_popup()
        else:
            self.search.clear()
            self.popup.open_popup(anchor)
            if self.list.count():
                self.list.setCurrentRow(0)


class FilterPanel(QWidget):
    accepted = Signal()
    finished = Signal(int)

    def __init__(self, state, defaults, parent=None):
        super().__init__(parent)
        self.defaults, self.index = defaults, state.index
        self.setObjectName('catalogFilterVeil')
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f'QWidget#catalogFilterVeil{{background:rgba(5,10,16,110);}} QFrame#catalogFilterCard{{background:{T["surface"]};border:1px solid {T["border"]};border-radius:16px;}}')
        self.card = QFrame(self)
        self.card.setObjectName('catalogFilterCard')
        root = QVBoxLayout(self.card)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        header = QHBoxLayout()
        title = QLabel('Фильтры')
        title.setStyleSheet('font-size:24px;font-weight:600;')
        font = title.font()
        font.setPixelSize(TYPE['section'])
        font.setBold(True)
        title.setFont(font)
        header.addWidget(title, 1)
        close = NexusButton('×', variant='quiet')
        close.setFixedWidth(36)
        close.setAccessibleName('Закрыть фильтры без применения')
        close.clicked.connect(self.reject)
        header.addWidget(close)
        root.addLayout(header)
        scroller = QScrollArea()
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setWidgetResizable(True)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        box = QVBoxLayout(body)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.content_type = CatalogComboBox(body)
        self.content_type.addItem('Моды', 'mod')
        self.content_type.setAccessibleName('Тип контента')
        self.content_type.setToolTip('Каталог устанавливает моды в выбранную сборку')
        type_row = QHBoxLayout()
        type_row.addWidget(QLabel('Тип контента'))
        type_row.addWidget(self.content_type, 1)
        box.addLayout(type_row)
        groups = QGridLayout()
        groups.setHorizontalSpacing(12)
        self.versions = TagSelection('Версия Minecraft', state.versions, body)
        self.loaders = TagSelection('Загрузчик', state.loaders, body)
        for col, (label, control) in enumerate((('Версия Minecraft', self.versions), ('Загрузчик', self.loaders))):
            groups.addWidget(QLabel(label), 0, col)
            groups.addWidget(control, 1, col)
            groups.setColumnStretch(col, 1)
        box.addLayout(groups)
        box.addWidget(QLabel('Категории'))
        self.categories = TagSelection('Категории', state.categories, body)
        self.categories.hide()
        self.category_area = QWidget()
        self.category_flow = FlowLayout(self.category_area)
        box.addWidget(self.category_area)
        self.more_categories = NexusButton('Все категории', variant='quiet', chevron=True)
        self.more_categories.clicked.connect(lambda: self.categories.showPopup(anchor=self.more_categories))
        box.addWidget(self.more_categories)
        self.categories.changed.connect(self._refresh_categories)
        self.extra_button = NexusButton('Дополнительные фильтры', variant='quiet', chevron=True)
        self.extra_button.setCheckable(True)
        self.extra = QWidget()
        extra_layout = QVBoxLayout(self.extra)
        extra_layout.setContentsMargins(0, 0, 0, 0)
        extra_layout.setSpacing(8)
        self.environment = CatalogComboBox(self.extra)
        self.environment.setAccessibleName('Среда выполнения')
        for value, label in ENVIRONMENTS.items():
            self.environment.addItem(label, value)
        self.environment.setCurrentIndex(self.environment.findData(state.environment))
        extra_layout.addWidget(QLabel('Среда выполнения'))
        extra_layout.addWidget(self.environment)
        self.open_source = NexusButton('Открытый исходный код', variant='chip')
        self.open_source.setCheckable(True)
        self.open_source.setChecked(state.open_source is True)
        self.archived = NexusButton('Не показывать архивные проекты', variant='chip')
        self.archived.setCheckable(True)
        self.archived.setChecked(state.exclude_archived)
        extra_layout.addWidget(self.open_source)
        extra_layout.addWidget(self.archived)
        self.extra_button.toggled.connect(self._toggle_extra)
        box.addWidget(self.extra_button)
        box.addWidget(self.extra)
        self.extra.hide()
        self.metadata_status = QLabel('Загрузка списков…')
        self.metadata_status.setObjectName('muted')
        self.metadata_status.setWordWrap(True)
        box.addWidget(self.metadata_status)
        self.retry = NexusButton('Повторить загрузку', variant='quiet')
        self.retry.hide()
        box.addWidget(self.retry)
        box.addStretch()
        scroller.setWidget(body)
        root.addWidget(scroller, 1)
        footer = QHBoxLayout()
        reset = NexusButton('Сбросить', variant='quiet')
        reset.clicked.connect(self.reset)
        cancel = NexusButton('Отмена', variant='secondary')
        cancel.clicked.connect(self.reject)
        apply = NexusButton('Применить', variant='primary')
        apply.clicked.connect(self.accept)
        footer.addWidget(reset)
        footer.addStretch()
        footer.addWidget(cancel)
        footer.addWidget(apply)
        root.addLayout(footer)
        self.extra_button.setChecked(bool(state.environment or state.open_source or state.exclude_archived))
        self._refresh_categories()
        owner = self.parentWidget()
        if owner is not None:
            owner.installEventFilter(self)
        self.hide()

    def _refresh_categories(self):
        existing = getattr(self, '_category_buttons', {})
        while self.category_flow.count():
            self.category_flow.takeAt(0)
        self._category_buttons = {}
        values = [self.categories.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.categories.list.count())]
        priority = ['optimization', 'technology', 'adventure', 'magic', 'worldgen', 'utility', 'decoration', 'storage']
        visible = list(dict.fromkeys([*self.categories.selected(), *(v for v in priority if v in values), *values]))[:8]
        for value in visible:
            button = existing.pop(value, None)
            if button is None:
                button = NexusButton(tag_label(value), variant='chip')
                button.setCheckable(True)
                button.clicked.connect(lambda _checked=False, tag=value: self.categories.toggle_value(tag))
            self._category_buttons[value] = button
            button.setChecked(value in self.categories.selected())
            button.setAccessibleName('Категория: ' + tag_label(value))
            self.category_flow.addWidget(button)
        for button in existing.values():
            button.hide()
            button.deleteLater()
        remaining = max(0, len(values) - len(visible))
        self.more_categories.setText(f'Ещё {remaining}…' if remaining else 'Все категории')
        self.more_categories.setVisible(bool(values))
        self.category_area.updateGeometry()
        self._place()

    def _toggle_extra(self, expanded):
        self.extra.setVisible(expanded)
        self._place()

    def _place(self):
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        width = min(560, max(1, parent.width() - 24))
        height = min(parent.height() - 24, 540 + (150 if self.extra_button.isChecked() else 0))
        self.category_area.setMinimumHeight(self.category_flow.heightForWidth(max(1, width - 40)))
        self.card.setGeometry(parent.width() - width - 12, 12, width, max(220, height))

    def open(self):
        self._place()
        self.show()
        self.raise_()
        self._event_targets = [self, *self.findChildren(QWidget)]
        for target in self._event_targets:
            target.installEventFilter(self)
        self.versions.setFocus(Qt.FocusReason.OtherFocusReason)

    def _close_popups(self):
        for control in (self.content_type, self.versions, self.loaders, self.categories, self.environment):
            control.popup.close_popup()
            control.popup.deleteLater()

    def accept(self):
        self.accepted.emit()
        self._finish(1)

    def reject(self):
        self._finish(0)

    def _finish(self, result):
        self._close_popups()
        for target in getattr(self, '_event_targets', ()):
            if isValid(target):
                target.removeEventFilter(self)
        self._event_targets = []
        self.hide()
        self.finished.emit(result)
        parent = self.parentWidget()
        if parent is not None and hasattr(parent, 'filters_button'):
            getattr(parent, 'filters_button').setFocus(Qt.FocusReason.OtherFocusReason)

    def mousePressEvent(self, event):
        if not self.card.geometry().contains(event.position().toPoint()):
            self.reject()
        event.accept()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self._place()
        if self.isVisible() and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.reject()
                return True
            if event.key() == Qt.Key.Key_Tab and not any(control.popup.isVisible() for control in (self.content_type, self.versions, self.loaders, self.categories, self.environment)):
                widgets = [w for w in self.card.findChildren(QWidget) if w.isVisible() and w.focusPolicy() != Qt.FocusPolicy.NoFocus]
                if widgets:
                    focused = QApplication.focusWidget()
                    index = widgets.index(focused) if focused in widgets else -1
                    direction = -1 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
                    widgets[(index + direction) % len(widgets)].setFocus(Qt.FocusReason.TabFocusReason)
                    return True
        return False

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.accept()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.reject()
            event.accept()
        else:
            super().keyPressEvent(event)

    def state(self):
        return ModrinthFilterState(versions=self.versions.selected(), loaders=self.loaders.selected(),
                                  categories=self.categories.selected(), environment=self.environment.currentData() or '',
                                  open_source=True if self.open_source.isChecked() else None,
                                  exclude_archived=self.archived.isChecked(), index=self.index)

    def set_metadata(self, metadata, error=''):
        for field in ('versions', 'loaders', 'categories'):
            getattr(self, field).set_values(metadata.get(field, []))
        self.metadata_status.setText('Списки недоступны. Попробуйте ещё раз.' if error else '')
        self.metadata_status.setToolTip(error)
        self.metadata_status.setVisible(bool(error))
        self.retry.setVisible(bool(error))
        self._refresh_categories()

    def reset(self):
        self.index = self.defaults.index
        for field in ('versions', 'loaders', 'categories'):
            selector = getattr(self, field)
            selector.search.clear()
            selector._selected = getattr(self.defaults, field)
            values = [selector.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(selector.list.count())]
            selector.set_values(values)
        self.environment.setCurrentIndex(0)
        self.open_source.setChecked(False)
        self.archived.setChecked(False)
        self.extra_button.setChecked(False)
