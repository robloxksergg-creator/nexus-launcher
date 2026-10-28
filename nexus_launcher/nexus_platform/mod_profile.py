"""Native mod presentation; project content cannot execute HTML or read files."""
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy
from .artwork import landscape
from .project_content import ProjectBody  # noqa: F401


class ModTitle(QPushButton):
    def __init__(self, title):
        super().__init__(title)
        self.caption = title
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.setText(self.fontMetrics().elidedText(self.caption, Qt.ElideRight, self.width()))


class ModRow(QWidget):
    def __init__(self, hit, instance, open_project, install_project, *, context=None):
        super().__init__()
        self.setObjectName('modRow')
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(18)
        self.icon = QLabel()
        self.icon.setObjectName('modIcon')
        self.icon.setFixedSize(80, 80)
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setPixmap(landscape(hit.get('project_id', hit['title']), 80, 80))
        root.addWidget(self.icon)
        text = QVBoxLayout()
        title_row = QHBoxLayout()
        title = ModTitle(hit['title'])
        title.setObjectName('modTitle')
        title.setAccessibleName('Открыть страницу мода ' + hit['title'])
        title.setToolTip(hit['title'])
        title.clicked.connect(open_project)
        author = QLabel('от ' + hit['author'] if hit.get('author') else '')
        author.setTextFormat(Qt.PlainText)
        author.setObjectName('muted')
        title_row.addWidget(title, 1)
        title_row.addWidget(author)
        text.addLayout(title_row)
        description = QLabel(hit.get('description', ''))
        description.setTextFormat(Qt.PlainText)
        description.setObjectName('modDescription')
        description.setWordWrap(True)
        description.setMaximumHeight(42)
        text.addWidget(description)
        tags = ' · '.join(hit.get('display_categories', hit.get('categories', []))[:3]) or 'Моды'
        downloads = int(hit.get('downloads') or 0)
        number = f'{downloads / 1_000_000:.1f} млн' if downloads >= 1_000_000 else f'{downloads / 1000:.1f} тыс' if downloads >= 1000 else str(downloads)
        published = QDateTime.fromString(hit.get('date_modified', ''), Qt.ISODate)
        date = published.toLocalTime().toString('dd.MM.yyyy') if published.isValid() else ''
        if context is None:
            context = f'Minecraft {instance.minecraft_version} · {instance.loader.title()}' if instance else ''
        metadata = QLabel('   ·   '.join(part for part in (tags, '↓ ' + number if 'downloads' in hit else '', date, context) if part))
        metadata.setTextFormat(Qt.PlainText)
        metadata.setObjectName('modMetadata')
        metadata.setWordWrap(True)
        text.addWidget(metadata)
        root.addLayout(text, 1)
        self.install = QPushButton('Установить')
        self.install.setObjectName('primaryAction')
        self.install.clicked.connect(install_project)
        self.install.setEnabled(bool(instance and instance.loader != 'vanilla'))
        root.addWidget(self.install, 0, Qt.AlignTop)
