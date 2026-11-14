"""Shared bounded navy workspaces; presentation only, never service authority."""
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QLabel, QVBoxLayout, QMenu

from .theme_tokens import TOKENS, MOTION, WORKSPACE
from nexus_launcher.installer_completion import Backdrop


def monogram(text, size=64):
    """Neutral local identity until the provider's validated icon is available."""
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor('#203d59'))
    painter.drawRoundedRect(pixmap.rect(), 13, 13)
    painter.setPen(QColor('#a5d9ff'))
    font = QFont('Bahnschrift');font.setPixelSize(size//2);font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, str(text)[:1].upper() or '◇')
    painter.end()
    return pixmap


def outline_icon(kind, size=40):
    """Local vector symbols, independent of OS emoji/font fallback."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    paths = {
        'mods': 'M12 2 22 7v10l-10 5-10-5V7z M2 7l10 5 10-5 M12 12v10',
        'backups': 'M7 3h13v14H7z M4 7H2v15h14v-2 M10 7h7 M10 11h7',
        'saves': 'm2 5 7-3 7 3 6-3v17l-6 3-7-3-7 3z M9 2v17 M16 5v17',
        'resourcepacks': 'M3 3h8v8H3z M15 3h6v6h-6z M3 15h6v6H3z M13 13h8v8h-8z',
        'shaderpacks': 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10 M12 1v3 M12 20v3 M1 12h3 M20 12h3 M4 4l2 2 M18 18l2 2 M4 20l2-2 M18 6l2-2',
        'datapacks': 'm8 5-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18',
    }
    path = paths.get(kind, 'M10 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16 M16 16l6 6')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="{path}" fill="none" stroke="{WORKSPACE["accent"]}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    return pixmap


class BrandSurface(Backdrop):
    """Completion's folded-N backdrop, with optional owned build artwork."""
    def set_artwork(self, path, seed=''):
        from pathlib import Path
        from .artwork import load_artwork
        self._owned_art = load_artwork(path, seed) if path and Path(path).is_file() else None
        self.update()

    def paintEvent(self, event):
        if getattr(self, '_owned_art', None) is None:
            return super().paintEvent(event)
        from PySide6.QtGui import QPainter, QLinearGradient, QColor
        painter = QPainter(self)
        art = self._owned_art.scaled(self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.drawPixmap((self.width()-art.width())//2, (self.height()-art.height())//2, art)
        shade = QLinearGradient(0, 0, self.width(), 0)
        shade.setColorAt(0, QColor(7, 17, 30, 240))
        shade.setColorAt(1, QColor(7, 17, 30, 155))
        painter.fillRect(self.rect(), shade)
        painter.end()


def workspace_style():
    t = TOKENS
    w = WORKSPACE
    return f'''
    QWidget#instancePage, QWidget#modWorkspace {{background:{w['background']};}}
    QFrame#workspacePanel, QWidget#workspacePanel {{background:{w['surface']};border:1px solid {w['border']};border-radius:18px;}}
    QLabel#workspaceKicker {{color:#83c9ff;font-size:11px;letter-spacing:2px;font-weight:600;}}
    QLabel#workspaceTitle {{font-family:'Bahnschrift','Segoe UI';font-size:32px;font-weight:700;color:#eff6ff;}}
    QLabel#workspaceSection {{font-size:19px;font-weight:650;color:#e4effc;}}
    QLabel#workspaceMetric {{font-family:'Bahnschrift','Segoe UI';font-size:25px;font-weight:600;color:#b5dcff;}}
    QPushButton#primaryAction {{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 {w['primaryTop']},stop:1 {w['primaryBottom']});color:#071a2b;border:1px solid #9bdeff;border-radius:11px;padding:10px 18px;font-weight:700;}}
    QPushButton#primaryAction:hover {{background:#9bd9ff;}}
    QPushButton#primaryAction:disabled {{background:{t['surface']};color:{t['muted']};border-color:{t['border']};}}
    QPushButton:focus {{border:2px solid {t['accent']};}}
    QTabWidget::pane {{background:#0c1725;border:1px solid #263c52;border-radius:14px;top:4px;}}
    QTabBar::tab {{background:transparent;color:#a9bad0;border:0;border-radius:9px;padding:11px 13px;margin:0 3px 8px 0;}}
    QTabBar::tab:selected {{background:#213d5a;color:#e8f4ff;}}
    QTabBar::tab:hover {{background:#182c42;}}
    QListWidget {{background:#0c1725;border:1px solid #263c52;border-radius:12px;}}
    QProgressBar {{background:#1c3046;border:0;border-radius:4px;min-height:7px;max-height:7px;}}
    QProgressBar::chunk {{background:#81caff;border-radius:4px;}}
    QFrame#modSearchHeader {{background:#101e30;border:1px solid #294158;border-radius:18px;}}
    QFrame#modProfileHeader {{background:{w['surface']};border:1px solid {w['border']};border-radius:18px;}}
    QLabel#modProjectTitle {{font-family:'Bahnschrift','Segoe UI';font-size:28px;font-weight:650;}}
    QWidget#modRow {{background:#101e30;border:1px solid #294158;border-radius:14px;}}
    QWidget#modRow:hover {{background:#162b42;border-color:#5485ac;}}
    QFrame#installedModRow {{background:#101e30;border:1px solid #294158;border-radius:10px;}}
    QLabel#installedModName {{font-size:15px;font-weight:600;color:#dfecfb;}}
    QPushButton#diagnosticShortcut {{background:transparent;color:#9bd6ff;border:1px solid #375772;border-radius:7px;padding:5px 10px;font-size:11px;}}
    QPushButton#buildMoreAction {{background:#172c42;border:1px solid #3a5772;border-radius:10px;padding:0;font-size:22px;}}
    QPushButton#buildMoreAction:hover {{background:#294a69;border-color:#89c9ff;}}
    QCheckBox::indicator {{width:30px;height:18px;border-radius:9px;background:#33465c;border:1px solid #587087;}}
    QCheckBox::indicator:checked {{background:#68bfff;border-color:#a3ddff;}}
    QLabel#modDescription {{color:#c3d0df;font-size:14px;}}
    QLabel#modMetadata {{color:#95abc2;font-size:12px;}}
    '''


def workspace_menu(parent=None):
    menu=QMenu(parent)
    menu.setStyleSheet('''
        QMenu {background:#112237;color:#dceafa;border:1px solid #3b5873;border-radius:12px;padding:8px;font:13px "Segoe UI";}
        QMenu::item {padding:10px 28px 10px 14px;border-radius:7px;min-width:240px;}
        QMenu::item:selected {background:#264c6c;color:#eff8ff;}
        QMenu::item:disabled {color:#7b96af;}
        QMenu::separator {height:1px;background:#2e4760;margin:6px 10px;}
    ''')
    return menu


def panel(title, description='', parent=None):
    frame = QFrame(parent)
    frame.setObjectName('workspacePanel')
    box = QVBoxLayout(frame)
    box.setContentsMargins(22, 20, 22, 20)
    box.setSpacing(12)
    label = QLabel(title)
    label.setObjectName('workspaceSection')
    label.setWordWrap(True)
    box.addWidget(label)
    if description:
        copy = QLabel(description)
        copy.setObjectName('muted')
        copy.setWordWrap(True)
        box.addWidget(copy)
    return frame, box


def reveal(widget):
    """Finite transition; no running animation while idle, no layout motion."""
    hints = QGuiApplication.styleHints()
    if hints.property('reducedMotion') is True or widget.property('reducedMotion') is True:
        return
    ancestor = widget
    while ancestor is not None:
        config = getattr(getattr(ancestor, 'services', None), 'config', {})
        if config.get('reducedMotion', False):
            return
        ancestor = ancestor.parentWidget()
    existing = getattr(widget, '_workspace_reveal', None)
    if existing is not None:
        existing.stop()
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    effect.setEnabled(True)
    animation = existing or QPropertyAnimation(effect, b'opacity', widget)
    animation.setDuration(MOTION['normal'])
    animation.setStartValue(.35)
    animation.setEndValue(1.)
    animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    if existing is None:
        animation.finished.connect(lambda: effect.setEnabled(False))
    widget._workspace_reveal = animation
    animation.start()
