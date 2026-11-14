"""Shared native empty/loading/error presentation with real next actions."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout


class ContentState(QFrame):
    def __init__(self, title, description, action_label, callback, seed="content"):
        super().__init__()
        self.setObjectName('workspacePanel')
        from .workspace_visuals import workspace_style
        self.setStyleSheet(workspace_style())
        self.setMinimumHeight(190)
        self.setMaximumHeight(270)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)
        from .workspace_visuals import outline_icon
        symbol = QLabel()
        symbol.setPixmap(outline_icon(seed))
        symbol.setFixedSize(40, 40)
        root.addWidget(symbol)
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
