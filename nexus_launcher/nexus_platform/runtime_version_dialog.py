from PySide6.QtWidgets import QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QComboBox,QPushButton,QFormLayout
from nexus_launcher.themed_dialog import NexusDialog
from .presentation_style import stylesheet
from .workspace_visuals import workspace_style


class RuntimeVersionDialog(NexusDialog):
    def __init__(self,instance,parent=None):
        super().__init__(parent);self.setWindowTitle('Версия сборки');self.resize(560,380);self.setStyleSheet(stylesheet()+workspace_style())
        box=QVBoxLayout(self);box.setContentsMargins(24,24,24,24);box.setSpacing(16)
        title=QLabel('Изменить Minecraft и загрузчик');title.setObjectName('workspaceSection');box.addWidget(title)
        warning=QLabel('Моды и миры останутся на месте. Они могут быть несовместимы с новой версией. Создаётся копия настроек; для возврата мира после его запуска нужна отдельная резервная копия. Игра автоматически не запускается.')
        warning.setWordWrap(True);box.addWidget(warning)
        form=QFormLayout();self.game=QLineEdit(instance.minecraft_version);self.loader=QComboBox();self.loader.addItems(['vanilla','fabric','forge','neoforge']);self.loader.setCurrentText(instance.loader)
        self.version=QLineEdit(instance.loader_version);self.version.setPlaceholderText('Рекомендуемая, если известна')
        self.loader.currentTextChanged.connect(lambda value:self.version.setText(''))
        form.addRow('Minecraft',self.game);form.addRow('Загрузчик',self.loader);form.addRow('Версия загрузчика',self.version);box.addLayout(form)
        buttons=QHBoxLayout();buttons.addStretch();cancel=QPushButton('Отмена');cancel.setDefault(True);cancel.clicked.connect(self.reject)
        apply=QPushButton('Сохранить версию');apply.setObjectName('primaryAction');apply.clicked.connect(self.accept);buttons.addWidget(cancel);buttons.addWidget(apply);box.addLayout(buttons)
