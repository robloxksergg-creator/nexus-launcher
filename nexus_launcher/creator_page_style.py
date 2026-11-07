"""Creator application presentation, derived from the launcher's canonical tokens."""
from nexus_launcher.nexus_platform.theme_tokens import TOKENS,TYPE,RADIUS


def creator_page_style():
    t=TOKENS
    return f'''
    QDialog#creatorApplication {{ background:{t['background']}; }}
    QDialog#creatorApplication QLabel {{ color:{t['text']}; background:transparent; }}
    QDialog#creatorApplication QLabel#creatorEyebrow {{ color:{t['accent']}; font-size:{TYPE['metadata']}px; letter-spacing:2px; }}
    QDialog#creatorApplication QLabel#creatorHeading {{ font-family:'Bahnschrift','Segoe UI'; font-size:{TYPE['heading']}px; font-weight:600; }}
    QDialog#creatorApplication QLabel#creatorSectionTitle {{ font-size:{TYPE['section']}px; font-weight:600; }}
    QDialog#creatorApplication QLabel#creatorMuted {{ color:{t['muted']}; font-size:{TYPE['caption']}px; }}
    QDialog#creatorApplication QLabel#creatorFieldLabel {{ color:{t['muted']}; font-size:{TYPE['label']}px; }}
    QDialog#creatorApplication QLabel#creatorBadge {{ background:{t['wash']}; color:{t['accent']}; border:1px solid {t['border']}; border-radius:{RADIUS['control']}px; padding:6px 12px; font-size:{TYPE['caption']}px; }}
    QDialog#creatorApplication QLabel#creatorBadge[tone="warning"] {{ color:{t['warning']}; }}
    QDialog#creatorApplication QLabel#creatorBadge[tone="success"] {{ color:{t['success']}; }}
    QDialog#creatorApplication QFrame#creatorRail {{ background:{t['sidebar']}; border:1px solid {t['border']}; border-radius:{RADIUS['surface']}px; }}
    QDialog#creatorApplication QFrame#creatorReleaseTile {{ background:{t['wash']}; border:0; border-radius:{RADIUS['control']}px; }}
    QDialog#creatorApplication QFrame#creatorPlanCell {{ background:{t['sidebar']}; border:1px solid {t['border']}; border-radius:{RADIUS['control']}px; }}
    QDialog#creatorApplication QLabel#creatorPlanValue {{ font-size:{TYPE['body']}px; font-weight:600; }}
    QDialog#creatorApplication QLabel#creatorPreviewName {{ font-family:'Bahnschrift','Segoe UI'; font-size:{TYPE['section']}px; font-weight:600; }}
    QDialog#creatorApplication QLabel#creatorFeedback {{ color:{t['muted']}; font-size:{TYPE['caption']}px; }}
    QDialog#creatorApplication QFrame#creatorDivider {{ background:{t['border']}; min-height:1px; max-height:1px; border:0; }}
    QDialog#creatorApplication QWidget#creatorEditor, QDialog#creatorApplication QWidget#creatorFormPage, QDialog#creatorApplication QScrollArea {{ background:transparent; border:0; }}
    QDialog#creatorApplication QTabWidget::pane {{ border:0; background:transparent; }}
    QDialog#creatorApplication QTabBar::tab {{ padding:14px 16px; color:{t['muted']}; background:transparent; border:0; border-bottom:2px solid transparent; }}
    QDialog#creatorApplication QTabBar::tab:selected {{ color:{t['text']}; border-bottom:2px solid {t['accent']}; }}
    QDialog#creatorApplication QTabBar::tab:focus {{ background:{t['wash']}; }}
    QDialog#creatorApplication QLineEdit, QDialog#creatorApplication QPlainTextEdit, QDialog#creatorApplication QComboBox {{ background:{t['sidebar']}; border:1px solid {t['border']}; border-radius:{RADIUS['control']}px; padding:12px 14px; color:{t['text']}; selection-background-color:{t['wash']}; }}
    QDialog#creatorApplication QLineEdit:focus, QDialog#creatorApplication QPlainTextEdit:focus, QDialog#creatorApplication QComboBox:focus {{ border-color:{t['accent']}; }}
    QDialog#creatorApplication QPushButton {{ min-height:24px; padding:10px 16px; }}
    QDialog#creatorApplication QPushButton#creatorQuiet {{ color:{t['muted']}; border:1px solid {t['border']}; background:transparent; }}
    QDialog#creatorApplication QPushButton#creatorQuiet:hover {{ color:{t['text']}; background:{t['surface']}; }}
    QDialog#creatorApplication QPushButton#creatorLink {{ color:{t['muted']}; border:1px solid transparent; background:transparent; font-size:{TYPE['caption']}px; padding:8px 10px; }}
    QDialog#creatorApplication QPushButton#creatorLink:hover {{ color:{t['text']}; background:{t['sidebar']}; }}
    QDialog#creatorApplication QPushButton#creatorLink:disabled {{ color:{t['border']}; background:transparent; }}
    QDialog#creatorApplication QPushButton#creatorSecondary {{ background:{t['surface']}; border:1px solid {t['border']}; }}
    QDialog#creatorApplication QPushButton#creatorSubmit {{ background:{t['accent']}; color:{t['background']}; border:1px solid {t['accent']}; font-weight:600; }}
    QDialog#creatorApplication QPushButton#creatorSubmit:hover {{ background:{t['text']}; }}
    QDialog#creatorApplication QPushButton#creatorSubmit:disabled {{ background:{t['surface']}; color:{t['muted']}; border-color:{t['border']}; }}
    QDialog#creatorApplication QPushButton:disabled {{ color:{t['muted']}; }}
    QDialog#creatorApplication QPushButton:focus {{ border:1px solid {t['accent']}; }}
    QDialog#creatorApplication QCheckBox {{ spacing:10px; font-size:{TYPE['caption']}px; }}
    QDialog#creatorApplication QCheckBox:focus {{ color:{t['accent']}; }}
    '''
