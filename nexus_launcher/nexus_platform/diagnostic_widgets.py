"""Shared presentation entry for local pack diagnostics; no scan or mutation."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from .presentation_style import stylesheet


class DiagnosticEntryCard(QFrame):
    requested = Signal()

    def __init__(self, parent=None, *, managed=False):
        super().__init__(parent)
        self.setObjectName('diagnosticEntry')
        self.setStyleSheet(stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        eyebrow = QLabel('СОСТОЯНИЕ СБОРКИ')
        eyebrow.setObjectName('eyebrow')
        title = QLabel('Что мешает запуску?')
        title.setObjectName('cardTitle')
        title.setWordWrap(True)
        copy = QLabel('Посмотрите зависимости, вложенные JAR и подсказки из отчёта о сбое. '
                      + ('Управляемая сборка доступна здесь только для чтения.' if managed else
                         'Пробное изменение можно проверить в отдельной копии.'))
        copy.setObjectName('muted')
        copy.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(copy)
        actions = QHBoxLayout()
        scope = QLabel('Без запуска игры')
        scope.setObjectName('muted')
        actions.addWidget(scope, 1)
        self.open_button = QPushButton('Открыть диагностику')
        self.open_button.setObjectName('primaryAction')
        self.open_button.clicked.connect(self.requested)
        actions.addWidget(self.open_button)
        layout.addLayout(actions)
