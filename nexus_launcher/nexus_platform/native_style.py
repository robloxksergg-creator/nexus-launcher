"""Native fallback surfaces follow the shared palette, including scrollbars."""
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QDialog, QProxyStyle, QStyle, QStyleFactory, QPushButton, QToolButton

from .theme_tokens import TOKENS, TYPE


class NexusNativeStyle(QProxyStyle):
    def polish(self, target):
        result = super().polish(target)
        if isinstance(target, QDialog):
            from .dialog_chrome import watch_dialog
            watch_dialog(target)
        return result

    def drawPrimitive(self, element, option, painter, widget=None):
        # The scoped focus-visible tracker/QSS owns the accessible focus ring.
        # Suppress the OS dotted rectangle inside the button caption.
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect and isinstance(widget, (QPushButton, QToolButton)):
            return
        super().drawPrimitive(element, option, painter, widget)


def install_native_style(app):
    if app is None or getattr(app, '_nexus_native_style', None) is not None:
        return
    style = NexusNativeStyle(QStyleFactory.create('Fusion'))
    app.setStyle(style)
    app._nexus_native_style = style
    palette = QPalette()
    for role, token in (
        ('Window', 'background'), ('Base', 'sidebar'), ('AlternateBase', 'surface'),
        ('Button', 'surface'), ('WindowText', 'text'), ('Text', 'text'),
        ('ButtonText', 'text'), ('Highlight', 'wash'), ('HighlightedText', 'accent'),
        ('ToolTipBase', 'surface'), ('ToolTipText', 'text'), ('Mid', 'border'),
        ('Light', 'border'), ('Dark', 'background'), ('Shadow', 'background'),
    ):
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(TOKENS[token]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(TOKENS['muted']))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(TOKENS['muted']))
    app.setPalette(palette)
    font = QFont('Segoe UI')
    font.setPixelSize(TYPE['body'])
    app.setFont(font)
