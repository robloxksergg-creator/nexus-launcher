"""Presentation adapters for retained download, loading and error owners."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from .artwork import ArtworkSurface


def polish_downloads(page):
    """Recompose the original empty controls; preserve states and signals."""
    root = page.layout()
    root.setContentsMargins(32, 32, 32, 32)
    root.setSpacing(24)
    heading = page.findChild(QLabel, "pageTitle")
    heading.setText("Загрузки")
    old = page.empty
    controls = []
    while old.layout().count():
        item = old.layout().takeAt(0)
        if item.widget():
            controls.append(item.widget())
    hero = ArtworkSurface()
    hero.set_artwork("", "downloads")
    hero.setMinimumHeight(220)
    hero.setMaximumHeight(260)
    layout = QVBoxLayout(hero)
    layout.setContentsMargins(24, 24, 24, 24)
    layout.addStretch()
    for control in controls:
        if control.objectName() == "emptyIcon":
            control.hide()
            continue
        if isinstance(control, QLabel):
            control.setAlignment(Qt.AlignmentFlag.AlignLeft)
            control.setWordWrap(True)
            if control is page.empty_title:
                control.setObjectName('cardTitle')
            if control is not page.empty_title:
                control.setText("Установка и обновление появятся здесь, когда ты запустишь сборку или мир.")
            layout.addWidget(control)
        else:
            control.setText('Открыть каталог миров')
            control.setMinimumWidth(0)
            control.setMaximumWidth(16777215)
            layout.addWidget(control, 0, Qt.AlignmentFlag.AlignLeft)
    page.states.removeWidget(old)
    page.states.addWidget(hero)
    page.empty = hero
    page.states.setCurrentWidget(hero)
    old.hide()
    old.deleteLater()
    for label in (page.failure_file, page.failure_reason, page.detail, page.telemetry):
        label.setWordWrap(True)
    page.failure.setObjectName("downloadActive")
    page.failure.layout().setContentsMargins(32, 32, 32, 32)
    page.failure.layout().setSpacing(16)
