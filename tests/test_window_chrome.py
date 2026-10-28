import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout

from nexus_launcher.nexus_platform.window_chrome import (
    TitleBar,
    create_resize_edges,
    position_resize_edges,
)


@pytest.fixture(scope="session", autouse=True)
def keep_application_alive():
    app = QApplication.instance() or QApplication([])
    yield app


def test_restore_repeated_cycles_and_minimize():
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
    window.resize(700, 500)
    title = TitleBar(window)
    window.setCentralWidget(title)
    window.show()
    try:
        for _ in range(3):
            title.maximize.click()
            app.processEvents()
            assert window.isMaximized()
            title.maximize.click()
            QTest.qWait(120)
            assert not window.isMaximized()
            assert not window.isFullScreen()
            assert window.width() < window.screen().availableGeometry().width()
        title.minimize.click()
        app.processEvents()
        assert window.isMinimized()
        window.showNormal()
        app.processEvents()
        assert not window.isMinimized()
    finally:
        window.close()


def test_title_controls_full_hit_area_keyboard_and_close():
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
    window.resize(700, 500)
    root = QWidget()
    layout = QVBoxLayout(root)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    window.title_bar = TitleBar(window)
    layout.addWidget(window.title_bar)
    layout.addWidget(QWidget(), 1)
    window.setCentralWidget(root)
    window.resize_edges = create_resize_edges(window)
    window.show()
    app.processEvents()
    position_resize_edges(window)
    title = window.title_bar
    try:
        for control in (title.minimize, title.maximize, title.close_button):
            assert control.accessibleName() and control.toolTip()
            for point in (
                QPoint(2, 2),
                QPoint(control.width() - 2, 2),
                control.rect().center(),
            ):
                assert app.widgetAt(control.mapToGlobal(point)) is control
        QTest.mouseClick(title.minimize, Qt.LeftButton, pos=QPoint(2, 2))
        app.processEvents()
        assert window.isMinimized()
        window.showNormal()
        app.processEvents()
        title.maximize.setFocus(Qt.TabFocusReason)
        QTest.keyClick(title.maximize, Qt.Key_Return)
        app.processEvents()
        assert window.isMaximized()
        title.sync()
        assert title.maximize.symbol == "restore"
        assert title.maximize.property("windowExpanded")
        assert title.maximize.keyboard_focus
        QTest.keyClick(title.maximize, Qt.Key_Space)
        QTest.qWait(120)
        assert not window.isMaximized()
        title.sync()
        position_resize_edges(window)
        title.close_button.setFocus(Qt.TabFocusReason)
        QTest.keyClick(title.close_button, Qt.Key_Return)
        app.processEvents()
        assert not window.isVisible()
    finally:
        window.close()


def test_restore_keeps_user_geometry_and_button_double_click_does_not_bubble():
    app = QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
    window.setGeometry(120, 100, 700, 500)
    title = TitleBar(window)
    window.setCentralWidget(title)
    window.show()
    app.processEvents()
    before = window.geometry()
    try:
        title.maximize.click()
        app.processEvents()
        assert window.isMaximized()
        QTest.mouseDClick(title.maximize, Qt.LeftButton)
        app.processEvents()
        assert window.isMaximized()
        title.maximize.click()
        QTest.qWait(150)
        assert not window.isMaximized()
        assert window.geometry() == before
        title.maximize.click()
        app.processEvents()
        title.maximize.click()
        window.move(180, 130)
        moved = window.pos()
        QTest.qWait(150)
        assert window.pos() == moved
        window.setGeometry(160, 140, 740, 520)
        app.processEvents()
        changed = window.geometry()
        title.maximize.click()
        app.processEvents()
        title.maximize.click()
        QTest.qWait(150)
        assert window.geometry() == changed
    finally:
        window.close()
