"""Style original Qt dialogs/menus without replacing their actions or validation."""
from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (
    QLabel, QLayout, QLineEdit, QMenu, QPushButton,
    QScrollArea, QStyleFactory, QVBoxLayout, QWidget,
)
from nexus_launcher.instance_ui import CreateInstanceDialog
from .presentation_style import stylesheet
from shiboken6 import isValid
import weakref


def polish_creation(dialog):
    if dialog.property('nexusPolished'):
        return
    dialog.setProperty('nexusPolished', True)
    dialog.setObjectName('createBuildDialog')
    dialog.setStyleSheet(stylesheet())
    root = dialog.layout()
    items = [root.takeAt(0) for _ in range(root.count())]
    form, toggle, advanced, footer = items
    root.setContentsMargins(28, 24, 28, 24)
    root.setSpacing(16)
    title = QLabel('Новая сборка')
    title.setObjectName('dialogTitle')
    root.addWidget(title)
    copy = QLabel('Свой Minecraft. Свои моды. Своя история.')
    copy.setObjectName('muted')
    root.addWidget(copy)
    scroller = QScrollArea()
    scroller.setObjectName('creationScroll')
    scroller.setWidgetResizable(True)
    scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    content = QWidget()
    body = QVBoxLayout(content)
    body.setContentsMargins(0, 8, 8, 8)
    body.setSpacing(16)
    body.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
    primary = form.layout()
    primary.setHorizontalSpacing(20)
    primary.setVerticalSpacing(14)
    primary.labelForField(dialog.template).setText('Шаблон')
    dialog.template.setToolTip('Шаблон настроек без предустановленных модов.')
    for combo in (dialog.loader, dialog.template):
        combo._popup_style = QStyleFactory.create('Fusion')
        combo.setStyle(combo._popup_style)
    body.addLayout(primary)
    body.addWidget(toggle.widget())
    body.addWidget(advanced.widget())
    advanced_form = advanced.widget().layout()
    advanced_form.setContentsMargins(0, 0, 0, 0)
    advanced_form.setHorizontalSpacing(20)
    advanced_form.setVerticalSpacing(12)
    advanced_form.labelForField(dialog.java).setText('Java')
    dialog.java.setPlaceholderText('Автоматически')
    advanced_form.labelForField(dialog.jvm).setText('Аргументы JVM')
    for position, caption in ((6, 'Окно игры и баннер'), (3, 'Производительность'), (0, 'Установка и оформление')):
        label = QLabel(caption)
        label.setObjectName('formSection')
        advanced_form.insertRow(position, label)
    for field in dialog.findChildren(QLineEdit):
        field.setClearButtonEnabled(True)
        label = primary.labelForField(field) or advanced_form.labelForField(field)
        if label:
            label.setBuddy(field)
            field.setAccessibleName(label.text())
    for field in (dialog.loader, dialog.template, dialog.memory, dialog.resolution_width, dialog.resolution_height):
        label = primary.labelForField(field) or advanced_form.labelForField(field)
        if label:
            label.setBuddy(field)
            field.setAccessibleName(label.text())
    body.addStretch()
    scroller.setWidget(content)
    root.addWidget(scroller, 1)
    root.addLayout(footer.layout())
    create = dialog.findChild(QPushButton, 'playLarge')
    create.setObjectName('primaryAction')
    create.setText('Создать сборку')
    create.setDefault(True)
    toggle.widget().setObjectName('advancedToggle')
    def fit(expanded):
        available = dialog.screen().availableGeometry()
        dialog.setMinimumWidth(min(660, available.width() - 80))
        dialog.setMaximumHeight(max(400, available.height() - 80))
        chrome_height = dialog.title_bar.height() if hasattr(dialog, 'title_bar') else 0
        dialog.resize(dialog.minimumWidth(), min((660 if expanded else 500) + chrome_height, dialog.maximumHeight()))
        toggle.widget().setText('Дополнительные настройки ▴' if expanded else 'Дополнительные настройки ▾')
    toggle.widget().toggled.connect(lambda expanded: QTimer.singleShot(0, lambda: fit(expanded)))
    fit(False)
    # Object names changed while the original dialog was already being shown.
    dialog.setStyleSheet(stylesheet())


def polish_menu(menu):
    if menu.property('nexusPolished'):
        return
    menu.setProperty('nexusPolished', True)
    menu.setStyleSheet(stylesheet())
    menu.setMinimumWidth(300)
    actions = menu.actions()
    # All original actions/connections remain; destructive backup action is separated.
    for action in actions:
        if action.text() == 'Удалить резервную копию…':
            menu.insertSeparator(action)
            following = actions[actions.index(action) + 1]
            menu.insertSeparator(following)


class NativePresentation(QObject):
    def __init__(self, host, library):
        super().__init__(host)
        self.library = library
        self._tracked = weakref.WeakSet([library])
        library.installEventFilter(self)

    def close(self):
        for widget in tuple(self._tracked):
            if isValid(widget):
                widget.removeEventFilter(self)
        self._tracked.clear()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ChildPolished and watched is self.library:
            child = event.child()
            if isValid(child) and isinstance(child, (CreateInstanceDialog, QMenu)):
                self._tracked.add(child)
                child.installEventFilter(self)
            return False
        if event.type() == QEvent.Type.Show:
            if isinstance(watched, CreateInstanceDialog) and watched.parentWidget() is self.library:
                polish_creation(watched)
            elif isinstance(watched, QMenu) and watched.parentWidget() is self.library:
                polish_menu(watched)
        return False
