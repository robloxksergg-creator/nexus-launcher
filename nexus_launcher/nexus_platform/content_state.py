"""Shared native empty/loading/error presentation with real next actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout

from .artwork import ArtworkSurface


class ContentState(ArtworkSurface):
    def __init__(self, title, description, action_label, callback, seed="content"):
        super().__init__()
        self.set_artwork("", seed)
        self.setMinimumHeight(220)
        self.setMaximumHeight(260)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.title.setWordWrap(True)
        root.addWidget(self.title)
        self.description = QLabel(description)
        self.description.setObjectName("muted")
        self.description.setWordWrap(True)
        root.addWidget(self.description)
        self.action = QPushButton(action_label)
        self.action.setObjectName("primaryAction")
        self.action.clicked.connect(callback)
        root.addWidget(self.action, 0, Qt.AlignmentFlag.AlignLeft)
        root.addStretch()
