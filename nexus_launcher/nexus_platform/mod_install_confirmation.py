"""Explicit consent for a resolved mod plan; dismissal never installs files."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton
from .workspace_visuals import workspace_style


class ModInstallConfirmation(QDialog):
    def __init__(self, instance_name, project_id, plan, parent=None, *, requested_projects=None):
        super().__init__(parent)
        self.setWindowTitle('Установка модов')
        self.resize(580,440)
        self.setMinimumSize(460,340)
        self.setStyleSheet(workspace_style())
        layout=QVBoxLayout(self);layout.setContentsMargins(24,24,24,24);layout.setSpacing(16)
        heading=QLabel('Скачать выбранные моды и зависимости?' if requested_projects else 'Установить мод и его зависимости?');heading.setObjectName('workspaceSection');heading.setWordWrap(True);layout.addWidget(heading)
        explanation=QLabel(f'В сборку «{instance_name}» будут добавлены перечисленные ниже моды. Зависимости нужны для их работы. Отмена не запускает установку.');explanation.setWordWrap(True);layout.addWidget(explanation)
        self.items=QListWidget()
        for version in plan:
            role='Выбранный мод' if version.get('project_id') in (requested_projects or [project_id]) else 'Обязательная зависимость'
            self.items.addItem(f"{role} · {version.get('name') or version.get('project_id', '')}")
        layout.addWidget(self.items,1)
        foot=QLabel('Файлы проверяются по SHA-512. Установка не запускает игру.');foot.setWordWrap(True);layout.addWidget(foot)
        actions=QHBoxLayout();actions.addStretch()
        self.cancel=QPushButton('Отмена');self.cancel.clicked.connect(self.reject);self.cancel.setDefault(True)
        self.confirm=QPushButton(f'Установить · {len(plan)}');self.confirm.setObjectName('primaryAction');self.confirm.setAutoDefault(False);self.confirm.clicked.connect(self.accept)
        actions.addWidget(self.cancel);actions.addWidget(self.confirm);layout.addLayout(actions);self.cancel.setFocus()
