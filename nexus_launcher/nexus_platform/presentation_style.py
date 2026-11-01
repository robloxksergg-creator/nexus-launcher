"""One canonical NEXUS stylesheet, independent of the legacy shell stylesheet."""
from .theme_tokens import TOKENS, TYPE, RADIUS


def stylesheet():
    t = TOKENS
    return f"""
    QWidget {{ color:{t['text']}; font-family:'Segoe UI'; font-size:{TYPE['body']}px; }}
    QMainWindow, QWidget#platformRoot, QStackedWidget#platformPages {{ background:{t['background']}; }}
    QLabel {{ background:transparent; border:0; }}
    QFrame#nexusSidebar {{ background:{t['sidebar']}; border-right:1px solid {t['border']}; }}
    QLabel#nexusBrand {{ font-size:23px; font-weight:800; }}
    QLabel#sidebarCaption {{ color:{t['muted']}; font-size:10px; }}
    QPushButton, QToolButton {{ background:{t['surface']}; border:1px solid transparent; border-radius:{RADIUS['control']}px; padding:8px 14px; min-height:20px; }}
    QPushButton:hover, QToolButton:hover {{ background:{t['hover']}; border-color:{t['accent']}; }}
    QPushButton:pressed, QToolButton:pressed {{ background:{t['wash']}; }}
    QPushButton:disabled, QToolButton:disabled {{ color:{t['muted']}; background:{t['surface']}; border-color:{t['border']}; }}
    QPushButton[focusVisible="true"], QToolButton[focusVisible="true"], QLineEdit:focus, QComboBox:focus {{ border:2px solid {t['accent']}; }}
    QToolButton#sidebarNavigation {{ text-align:left; padding:0 14px; border:0; color:{t['muted']}; background:transparent; }}
    QToolButton#sidebarNavigation[focusVisible="true"] {{ border:2px solid {t['accent']}; }}
    QToolButton#sidebarNavigation:hover {{ background:{t['surface']}; color:{t['text']}; }}
    QToolButton#sidebarNavigation[dataActive="true"] {{ background:{t['wash']}; color:{t['accent']}; }}
    QFrame#platformTitleBar {{ background:{t['background']}; border-bottom:1px solid {t['border']}; }}
    QLabel#titleContext {{ color:{t['muted']}; font-size:12px; }}
    QPushButton#windowControl {{ background:transparent; border:0; padding:0; font-size:16px; }}
    QToolButton#settingsSquare {{ padding:0; }}
    QPushButton#windowControl:hover {{ background:{t['hover']}; }}
    QPushButton#windowControl[closeControl="true"]:hover {{ background:#923c4b; }}
    QLabel#pageTitle, QLabel#settingsHeading, QLabel#emptyTitle {{ font-family:'Bahnschrift','Segoe UI'; font-size:{TYPE['heading']}px; font-weight:650; }}
    QLabel#cardTitle, QLabel#tileTitle, QLabel#downloadTitle {{ font-size:19px; font-weight:650; }}
    QLabel#muted, QLabel#worldStatus, QLabel#heroStatus, QLabel#heroMeta, QLabel#clientStatus {{ color:{t['muted']}; }}
    QLabel#eyebrow, QLabel#sectionTitle {{ color:{t['accent']}; font-size:10px; letter-spacing:2px; }}
    QFrame#contentCard, QFrame#downloadActive {{ background:{t['surface']}; border:0; border-radius:{RADIUS['surface']}px; }}
    QFrame#nexusHero {{ background:{t['surface']}; border-radius:14px; }}
    QFrame#nexusHeroOverlay {{ background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 rgba(11,20,26,230),stop:.55 rgba(11,20,26,110),stop:1 rgba(11,20,26,0)); }}
    QLabel#nexusHeroTitle {{ color:#ffffff; font-size:55px; font-weight:750; }}
    QLabel#heroDescription {{ color:#c4ced4; font-size:16px; }}
    QPushButton#primaryAction {{ background:{t['accent']}; color:{t['background']}; font-weight:650; border:0; }}
    QPushButton#primaryAction[focusVisible="true"] {{ border:2px solid {t['background']}; }}
    QPushButton#windowControl[focusVisible="true"] {{ border:2px solid {t['accent']}; }}
    QPushButton#primaryAction:hover {{ background:#b3ceff; }}
    QPushButton#primaryAction:disabled {{ background:{t['surface']}; color:{t['muted']}; }}
    QPushButton#worldTile {{ background:{t['surface']}; padding:0; text-align:left; }}
    QPushButton#worldTile[selected="true"], QPushButton#filterChip[dataActive="true"] {{ background:{t['wash']}; border-color:{t['accent']}; }}
    QFrame#profileCover {{ background:{t['wash']}; border:1px solid {t['border']}; border-radius:14px; }}
    QLineEdit, QComboBox, QPlainTextEdit, QSpinBox, QDoubleSpinBox {{ background:{t['sidebar']}; border:1px solid {t['border']}; border-radius:8px; padding:10px; selection-background-color:{t['wash']}; }}
    QComboBox QAbstractItemView, QListWidget, QTreeWidget {{ background:{t['sidebar']}; color:{t['text']}; border:1px solid {t['border']}; selection-background-color:{t['wash']}; }}
    QTreeWidget::item {{ padding:6px; }}
    QTreeWidget::item:selected {{ background:{t['wash']}; color:{t['accent']}; }}
    QTreeWidget QHeaderView::section {{ background:{t['surface']}; color:{t['text']}; border:0; border-bottom:1px solid {t['border']}; padding:8px; }}
    QListWidget::item {{ padding:10px; border-radius:6px; }}
    QListWidget::item:selected {{ background:{t['wash']}; color:{t['accent']}; }}
    QFrame#diagnosticMetric {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:{RADIUS['surface']}px; }}
    QLabel#diagnosticNumber {{ font-family:'Bahnschrift','Segoe UI'; font-size:30px; font-weight:650; color:{t['accent']}; }}
    QLabel#diagnosticNumber[tone="warning"] {{ color:{t['warning']}; }}
    QLabel#diagnosticNumber[tone="muted"] {{ color:{t['muted']}; }}
    QLabel#diagnosticStatus {{ color:{t['muted']}; font-size:{TYPE['caption']}px; }}
    QListWidget#diagnosticFindings {{ border:0; background:transparent; outline:0; }}
    QListWidget#diagnosticFindings::item {{ background:{t['sidebar']}; border:1px solid {t['border']}; padding:10px 12px; border-radius:{RADIUS['control']}px; }}
    QListWidget#diagnosticFindings::item:hover {{ background:{t['surface']}; }}
    QListWidget#diagnosticFindings::item:selected {{ background:{t['wash']}; border-left:3px solid {t['accent']}; color:{t['text']}; }}
    QListWidget#diagnosticFindings:focus {{ border:1px solid {t['accent']}; }}
    QPlainTextEdit#diagnosticEvidence {{ background:{t['sidebar']}; border:1px solid {t['border']}; padding:14px; }}
    QSplitter::handle {{ background:transparent; }}
    QFrame#settingsShell, QStackedWidget#settingsPanels {{ background:{t['surface']}; border-radius:12px; }}
    QFrame#settingsWorkspace {{ background:{t['background']}; }}
    QFrame#settingsMenu {{ background:transparent; border:0; }}
    QFrame#settingsMain {{ background:{t['sidebar']}; border:0; border-radius:{RADIUS['surface']}px; }}
    QFrame#settingsMenu QListWidget {{ background:transparent; border:0; padding:0; }}
    QFrame#settingsMain QLabel#settingLine {{ background:transparent; border:0; border-bottom:1px solid {t['border']}; border-radius:0; padding:20px 0; }}
    QListWidget#settingsCategories {{ background:{t['sidebar']}; border:0; padding:8px; }}
    QLabel#settingLine, QLabel#settingsValue {{ background:{t['sidebar']}; border:1px solid {t['border']}; border-radius:8px; padding:12px; }}
    QTabWidget::pane {{ background:transparent; border:0; }}
    QTabBar::tab {{ background:transparent; color:{t['muted']}; border:0; border-bottom:2px solid transparent; padding:12px 16px; }}
    QTabBar::tab:selected {{ color:{t['accent']}; border-bottom-color:{t['accent']}; }}
    QTabBar::tab:hover {{ background:{t['hover']}; }}
    QCheckBox::indicator {{ width:18px; height:18px; border:1px solid {t['border']}; border-radius:5px; background:{t['sidebar']}; }}
    QCheckBox::indicator:checked {{ background:{t['accent']}; border:3px solid {t['wash']}; }}
    QProgressBar {{ background:{t['surface']}; border:0; border-radius:4px; min-height:8px; text-align:center; }}
    QProgressBar::chunk {{ background:{t['accent']}; border-radius:4px; }}
    QScrollArea {{ background:transparent; border:0; }}
    QScrollArea > QWidget > QWidget {{ background:transparent; }}
    QScrollBar:vertical {{ width:8px; background:{t['sidebar']}; margin:0; }}
    QScrollBar::handle:vertical {{ background:{t['border']}; min-height:28px; border-radius:3px; }}
    QScrollBar::handle:vertical:hover {{ background:{t['muted']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background:transparent; }}
    QScrollBar:horizontal {{ height:8px; background:{t['sidebar']}; margin:0; }}
    QScrollBar::handle:horizontal {{ background:{t['border']}; min-width:28px; border-radius:3px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width:0; background:transparent; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background:{t['sidebar']}; }}
    QDialog, QMenu {{ background:{t['sidebar']}; }}
    QDialog QLabel {{ font-size:{TYPE['body']}px; }}
    QWidget#instancePage, QFrame#instanceWorkspace {{ background:{t['background']}; border:0; }}
    QListWidget#instanceList, QListWidget#settingsCategories {{ border:0; background:transparent; }}
    QWidget#instancePage QListWidget {{ border:0; background:transparent; }}
    QSlider::groove:horizontal {{ background:{t['border']}; height:4px; border-radius:2px; }}
    QSlider::handle:horizontal {{ background:{t['accent']}; width:14px; margin:-5px 0; border-radius:7px; }}
    QListWidget#settingsCategories::item {{ padding:12px; }}
    QFrame#downloadActive QLabel#downloadTitle {{ font-size:{TYPE['section']}px; }}
    QLabel#emptyIcon {{ font-size:64px; color:{t['accent']}; }}
    QTextBrowser, QTextEdit {{ background:{t['background']}; color:{t['text']}; border:0; padding:20px; }}
    QMenu {{ border:1px solid {t['border']}; padding:8px; }}
    QMenu::item {{ padding:10px 20px; }}
    QMenu::item:selected {{ background:{t['wash']}; }}
    QMenu::item:disabled {{ color:{t['muted']}; }}
    QMenu::separator {{ height:1px; background:{t['border']}; margin:6px 12px; }}
    QMenu::item {{ border-radius:6px; }}
    QDialog#createBuildDialog {{ border:1px solid {t['border']}; }}
    QLabel#dialogTitle {{ font-family:'Bahnschrift','Segoe UI'; font-size:30px; font-weight:650; }}
    QLabel#formSection {{ color:{t['accent']}; font-size:13px; font-weight:650; padding-top:12px; }}
    QPushButton#advancedToggle {{ text-align:left; color:{t['accent']}; background:transparent; border:1px solid {t['border']}; }}
    QScrollArea#creationScroll {{ background:transparent; }}
    QFrame#modSearchHeader, QFrame#modProfileHeader {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:16px; }}
    QWidget#modRow {{ background:{t['surface']}; border:1px solid {t['border']}; border-radius:12px; }}
    QWidget#modRow:hover {{ background:{t['hover']}; }}
    QPushButton#modTitle {{ background:transparent; border:0; padding:0; font-size:19px; font-weight:650; text-align:left; }}
    QPushButton#modTitle:hover {{ color:{t['accent']}; }}
    QLabel#modDescription {{ color:{t['muted']}; font-size:14px; }}
    QLabel#modMetadata {{ color:{t['muted']}; font-size:12px; }}
    QLabel#modProjectTitle {{ font-family:'Bahnschrift','Segoe UI'; font-size:30px; font-weight:650; }}
    """
