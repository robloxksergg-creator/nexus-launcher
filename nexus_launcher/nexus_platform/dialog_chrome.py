"""App-owned dialogs reuse launcher chrome without replacing dialog semantics."""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QDialog, QFileDialog

from .window_chrome import TitleBar, create_resize_edges, position_resize_edges


class DialogChrome(QObject):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        dialog.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            position_resize_edges(self.dialog)
        return False


class DialogWatch(QObject):
    """Some Qt dialogs create their layouts lazily, after their initial polish."""
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        dialog.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.PolishRequest, QEvent.Type.ChildPolished, QEvent.Type.Show):
            visible = self.dialog.isVisible()
            install_dialog_chrome(self.dialog)
            if visible and not self.dialog.isVisible() and self.dialog.isWindow():
                self.dialog.show()
        return False


def watch_dialog(dialog):
    if not getattr(dialog, '_nexus_dialog_watch', None):
        dialog._nexus_dialog_watch = DialogWatch(dialog)
    install_dialog_chrome(dialog)


def install_dialog_chrome(dialog):
    # Embedded registration pages are QDialogs with Qt.Widget, not new windows.
    # OS file pickers are not app-owned title bars and keep their native contract.
    if (not isinstance(dialog, QDialog) or isinstance(dialog, QFileDialog)
            or not dialog.isWindow() or getattr(dialog, '_nexus_dialog_chrome', None)):
        return
    layout = dialog.layout()
    if layout is None or layout.menuBar() is not None:
        return
    dialog._nexus_dialog_chrome = True  # prevent re-entry while polishing children
    previous_height = dialog.size().height()
    minimum_height, maximum_height = dialog.minimumHeight(), dialog.maximumHeight()
    dialog.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
    dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
    dialog.title_bar = TitleBar(dialog, dialog=True)
    # QLayout reserves this area for both grid and box layouts. No fields, button
    # connections, default/escape buttons or modal results are reconstructed.
    layout.setMenuBar(dialog.title_bar)
    extra = dialog.title_bar.height()
    if maximum_height < 16777215:
        dialog.setMaximumHeight(maximum_height + extra)
    if minimum_height:
        dialog.setMinimumHeight(minimum_height + extra)
    dialog.resize(dialog.size().width(), previous_height + extra)
    dialog.resize_edges = create_resize_edges(dialog)
    dialog._nexus_dialog_chrome = DialogChrome(dialog)
    position_resize_edges(dialog)
