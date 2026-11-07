"""Private website applications through the existing launcher account session."""
import threading
from copy import deepcopy
from PySide6.QtCore import Signal,Qt,QUrl,QDateTime
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QScrollArea,QWidget,QLineEdit,QPlainTextEdit,QCheckBox,QMessageBox,QComboBox,QFrame,QTabWidget,QSizePolicy
from nexus_launcher.creator_page_contract import PAGE_LIMITS,page_from_project,validate_page_content
from nexus_launcher.creator_page_workspace import CreatorPageWorkspace
from nexus_launcher.nexus_account import SessionRejected
from nexus_launcher.creator_page_style import creator_page_style


def label(text='',name='creatorMuted'):
    value=QLabel(text)
    value.setObjectName(name)
    value.setTextFormat(Qt.PlainText)
    value.setWordWrap(True)
    return value


class CreatorPageDialog(QDialog):
    finished_operation=Signal(str,object,object)

    def __init__(self,client,profile,service,identifier,parent=None):
        super().__init__(parent)
        self.workspace=CreatorPageWorkspace(client,profile,service,identifier)
        self.busy=False
        self.content=None
        self.dirty=False
        self.setWindowTitle('NEXUS · Заявка на сайт и лаунчер')
        self.setObjectName('creatorApplication')
        self.setStyleSheet(creator_page_style())
        self.resize(1160,860)
        self.setMinimumSize(780,680)
        root=QVBoxLayout(self)
        root.setContentsMargins(28,24,28,24)
        root.setSpacing(12)
        heading=QHBoxLayout()
        introduction=QVBoxLayout()
        introduction.setSpacing(6)
        introduction.addWidget(label('NEXUS  /  CREATOR','creatorEyebrow'))
        introduction.addWidget(label('Страница вашего сервера','creatorHeading'))
        introduction.addWidget(label('Расскажите о своём мире. Подготовьте его к выпуску.'))
        heading.addLayout(introduction,1)
        self.badge=label('Подключение','creatorBadge')
        self.badge.setWordWrap(False)
        heading.addWidget(self.badge,0,Qt.AlignTop)
        root.addLayout(heading)
        tools=QHBoxLayout()
        self.copy_project=QPushButton('Взять из проекта')
        self.copy_project.setObjectName('creatorLink')
        self.association_toggle=QPushButton('Есть заявка на сайте?')
        self.association_toggle.setObjectName('creatorLink')
        self.association_toggle.setCheckable(True)
        self.reload=QPushButton('Обновить')
        self.reload.setObjectName('creatorLink')
        tools.addWidget(self.copy_project)
        tools.addWidget(self.association_toggle)
        tools.addStretch()
        tools.addWidget(self.reload)
        root.addLayout(tools)
        self.association_panel=QFrame()
        association=QVBoxLayout(self.association_panel)
        association.setContentsMargins(0,0,0,0)
        association.addWidget(label('Уже начали на сайте? Свяжите проект с существующей заявкой.'))
        association_row=QHBoxLayout()
        self.existing=QComboBox()
        self.existing.setAccessibleName('Существующая заявка аккаунта')
        self.existing.addItem('Новая заявка для этого проекта',None)
        self.attach=QPushButton('Связать заявку')
        self.attach.setObjectName('creatorSecondary')
        self.attach.clicked.connect(self.attach_existing)
        association_row.addWidget(self.existing,1);association_row.addWidget(self.attach)
        association.addLayout(association_row)
        self.association_panel.hide()
        self.association_toggle.toggled.connect(self.association_panel.setVisible)
        root.addWidget(self.association_panel)
        self.status=label('Загружаем кабинет аккаунта…','creatorFeedback')
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.status)
        body=QHBoxLayout()
        body.setSpacing(24)
        self.editor=QWidget()
        # The form already scrolls. Native style/font minimum hints must not
        # force the whole dialog taller than a compact desktop's work area.
        self.editor.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Ignored)
        self.editor.setObjectName('creatorEditor')
        editor_layout=QVBoxLayout(self.editor)
        editor_layout.setContentsMargins(0,0,0,0)
        self.tabs=QTabWidget()
        self.tabs.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Ignored)
        self.tabs.setDocumentMode(True)
        self.tabs.setAccessibleName('Разделы заявки')
        editor_layout.addWidget(self.tabs)
        self.fields={}
        labels=dict(name='Название',summary='Короткое описание',about='О мире',rules='Правила',team='Команда и авторы',address='Адрес сервера',version='Версия Minecraft',loader='Загрузчик',genre='Жанр',website='Существующий HTTPS-сайт · необязательно')
        groups=[('Страница','О вашем мире.','Название и описание, которые увидят ваши игроки.',('name','genre','summary','about')),
                ('Команда','Люди и правила вашего мира.','Укажите авторов и объясните, как устроено ваше сообщество.',('team','rules')),
                ('Подключение','Детали для игроков.','Укажите адрес, версию игры и загрузчик. Ссылка на сайт необязательна.',('address','version','loader','website'))]
        for tab,title,description,keys in groups:
            scroll=QScrollArea();scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            page=QWidget();page.setObjectName('creatorFormPage')
            form=QVBoxLayout(page);form.setContentsMargins(2,22,16,20);form.setSpacing(14)
            form.addWidget(label(title,'creatorSectionTitle'))
            form.addWidget(label(description))
            def field_block(key):
                block=QVBoxLayout();block.setSpacing(9)
                field=QPlainTextEdit() if key in ('about','rules','team') else QLineEdit()
                if isinstance(field,QPlainTextEdit):field.setFixedHeight(150 if key=='about' else 130)
                else:field.setMaxLength(PAGE_LIMITS[key]);field.setMinimumHeight(44)
                field.setAccessibleName(labels[key])
                field.setToolTip(f'До {PAGE_LIMITS[key]} символов')
                field.textChanged.connect(self.mark_dirty)
                caption=label(labels[key],'creatorFieldLabel');caption.setBuddy(field)
                block.addWidget(caption);block.addWidget(field)
                self.fields[key]=field
                return block
            paired=('name','genre') if tab=='Страница' else ('version','loader') if tab=='Подключение' else ()
            for key in keys:
                if paired and key==paired[0]:
                    pair=QHBoxLayout();pair.setSpacing(16)
                    for p in paired:pair.addLayout(field_block(p),1)
                    form.addLayout(pair)
                elif not paired or key!=paired[1]:form.addLayout(field_block(key))
            form.addStretch()
            scroll.setWidget(page);self.tabs.addTab(scroll,tab)
        release_page=QWidget();release_page.setObjectName('creatorFormPage')
        release_layout=QVBoxLayout(release_page);release_layout.setContentsMargins(4,26,20,20);release_layout.setSpacing(20)
        release_layout.addWidget(label('Ваш план выпуска.','creatorSectionTitle'))
        release_layout.addWidget(label('Площадки, доступ и даты из проекта. Обновить их можно кнопкой «Взять из проекта».'))
        release_grid=QGridLayout();release_grid.setSpacing(14)
        self.release_values={}
        for key,title,row,column,span in [('destination','Где появится сервер',0,0,1),('access','Доступ к сборке',0,1,1),('websiteAt','Выпуск сайта',1,0,1),('launcherAt','Выпуск в лаунчере',1,1,1),('serverAt','Объявление открытия сервера',2,0,2)]:
            cell=QFrame();cell.setObjectName('creatorPlanCell')
            cell_layout=QVBoxLayout(cell);cell_layout.setContentsMargins(16,16,16,16);cell_layout.setSpacing(8)
            cell_layout.addWidget(label(title,'creatorFieldLabel'))
            value=label('—','creatorPlanValue');value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            cell_layout.addWidget(value);self.release_values[key]=value
            release_grid.addWidget(cell,row,column,1,span)
        release_grid.setColumnStretch(0,1);release_grid.setColumnStretch(1,1)
        release_layout.addLayout(release_grid)
        self.plan=label('Даты указаны в местном времени.');release_layout.addWidget(self.plan)
        release_layout.addWidget(label('После проверки NEXUS отдельно назначает выпуск этой версии. Дата открытия — объявление для игроков, а не команда запуска сервера.'))
        self.reference=label('')
        self.reference.setTextInteractionFlags(Qt.TextSelectableByMouse)
        release_layout.addStretch();release_layout.addWidget(self.reference)
        release_scroll=QScrollArea();release_scroll.setWidgetResizable(True)
        release_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff);release_scroll.setWidget(release_page)
        self.tabs.addTab(release_scroll,'Выпуск')
        body.addWidget(self.editor,1)
        self.rail=QFrame();self.rail.setObjectName('creatorRail')
        rail=QVBoxLayout(self.rail);rail.setContentsMargins(22,22,22,22);rail.setSpacing(14)
        rail.addWidget(label('ВАШ МИР В NEXUS','creatorEyebrow'))
        self.preview_name=label('Новый сервер','creatorPreviewName');rail.addWidget(self.preview_name)
        self.preview_meta=label('');rail.addWidget(self.preview_meta)
        line=QFrame();line.setObjectName('creatorDivider');rail.addWidget(line)
        tile=QFrame();tile.setObjectName('creatorReleaseTile')
        tile_layout=QVBoxLayout(tile);tile_layout.setContentsMargins(16,16,16,16);tile_layout.setSpacing(6)
        tile_layout.addWidget(label('Площадки','creatorFieldLabel'))
        self.destination=label('—','creatorPreviewName');tile_layout.addWidget(self.destination)
        tile_layout.addSpacing(8);tile_layout.addWidget(label('Доступ к сборке','creatorFieldLabel'))
        self.access_label=label('—','creatorFieldValue');tile_layout.addWidget(self.access_label)
        rail.addWidget(tile)
        self.rail_dates=label('Даты пока не назначены.');rail.addWidget(self.rail_dates)
        rail.addStretch()
        rail.addWidget(label('Проверка вручную','creatorFieldLabel'))
        rail.addWidget(label('Сначала проверка NEXUS.\nПотом назначение выпуска.'))
        self.rail_scroll=QScrollArea();self.rail_scroll.setWidgetResizable(True)
        self.rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rail_scroll.setFixedWidth(286);self.rail_scroll.setWidget(self.rail)
        body.addWidget(self.rail_scroll)
        root.addLayout(body,1)
        line=QFrame();line.setObjectName('creatorDivider');root.addWidget(line)
        self.rights=QCheckBox('Подтверждаю права на тексты, оформление и материалы по ссылкам.')
        root.addWidget(self.rights)
        self.submission_hint=label('Сначала сохраните черновик.');root.addWidget(self.submission_hint)
        buttons=QHBoxLayout()
        self.save=QPushButton('Сохранить черновик')
        self.save.setObjectName('creatorSecondary')
        self.submit=QPushButton('На проверку  →')
        self.submit.setObjectName('creatorSubmit')
        self.withdraw=QPushButton('Отозвать для правок')
        self.withdraw.setObjectName('creatorQuiet')
        website=QPushButton('Кабинет на сайте  ↗');website.setObjectName('creatorLink')
        website.clicked.connect(lambda:QDesktopServices.openUrl(QUrl('https://nexusmc.flux-productions.com/profile')))
        close=QPushButton('Закрыть');close.setObjectName('creatorQuiet')
        close.clicked.connect(self.reject)
        buttons.addWidget(close);buttons.addWidget(self.withdraw);buttons.addStretch();buttons.addWidget(self.save);buttons.addWidget(self.submit)
        root.addLayout(buttons)
        tools.insertWidget(2,website)
        self.reload.clicked.connect(self.load)
        self.save.clicked.connect(lambda:self.write('save'))
        self.submit.clicked.connect(lambda:self.write('submit'))
        self.withdraw.clicked.connect(lambda:self.write('reopen'))
        self.copy_project.clicked.connect(self.use_project)
        self.rights.toggled.connect(lambda:self.controls())
        self.finished_operation.connect(self.complete)
        self.existing.currentIndexChanged.connect(lambda:self.controls())
        for button in self.findChildren(QPushButton):button.setAutoDefault(False)
        self.run('load',self.workspace.load)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'rail_scroll'):self.rail_scroll.setVisible(self.width()>=1040 and self.height()>=780)

    def mark_dirty(self):
        self.dirty=True
        self.controls()

    def controls(self):
        item=self.workspace.item if self.content else None
        editable=bool(self.content and self.content.get('mode','blocks')=='blocks' and (not item or item['state']=='DRAFT'))
        safe=not self.busy and self.workspace.loaded and not self.workspace.unknown
        self.editor.setEnabled(not self.busy and bool(self.content))
        for field in self.fields.values():field.setReadOnly(not (safe and editable))
        self.save.setEnabled(safe and editable)
        self.copy_project.setEnabled(safe and editable)
        complete=False
        if item:
            try:validate_page_content(item['content'],True);complete=True
            except ValueError:pass
        self.submit.setEnabled(safe and bool(item) and editable and complete and not self.dirty and self.rights.isChecked())
        self.withdraw.setEnabled(safe and bool(item) and item['state']=='SUBMITTED')
        self.rights.setEnabled(safe and editable)
        self.reload.setEnabled(not self.busy)
        self.existing.setEnabled(safe and self.workspace.link is None)
        self.attach.setEnabled(safe and self.workspace.link is None and self.existing.currentData() is not None)
        self.association_toggle.setEnabled(not self.busy and self.workspace.link is None)
        self.association_toggle.setText('Заявка связана' if self.workspace.link else 'Есть заявка на сайте?')
        self.withdraw.setVisible(bool(item and item['state']=='SUBMITTED'))
        self._sync_presentation(complete)

    def _sync_presentation(self,complete=False):
        item=self.workspace.item if self.content else None
        text,tone=('Синхронизация','normal') if self.busy else ('Проверьте данные','warning') if self.workspace.unknown else ('Рассмотрена','warning') if item and item.get('review') else ('На проверке','normal') if item and item['state']=='SUBMITTED' else ('Не сохранено','warning') if self.dirty else ('Черновик','normal') if item else ('Новая заявка','normal')
        self.badge.setText(text)
        if self.badge.property('tone')!=tone:
            self.badge.setProperty('tone',tone);self.badge.style().unpolish(self.badge);self.badge.style().polish(self.badge)
        self.preview_name.setText(self.fields['name'].text().strip() or 'Новый сервер')
        meta=' · '.join(self.fields[k].text().strip() for k in ('genre','version','loader') if self.fields[k].text().strip())
        self.preview_meta.setText(meta[:80]+('…' if len(meta)>80 else '') if meta else 'Жанр, версия игры и загрузчик')
        self.preview_meta.setToolTip(meta)
        plan=self.content.get('releasePlan') if self.content else None
        self.destination.setText({'both':'Сайт и лаунчер','website':'Сайт','launcher':'Лаунчер'}[plan['destination']] if plan else 'Не выбраны')
        self.access_label.setText({'PUBLIC':'Бесплатно','PAID':'Платно · оплата отдельно','PRIVATE':'Приватно · по приглашению'}[plan['access']] if plan else 'По плану проекта')
        self.release_values['destination'].setText(self.destination.text())
        self.release_values['access'].setText(self.access_label.text())
        for key in ('websiteAt','launcherAt','serverAt'):
            missing='Не объявлено' if key=='serverAt' else 'По согласованию'
            if plan and (key=='websiteAt' and plan['destination']=='launcher' or key=='launcherAt' and plan['destination']=='website'):missing='Площадка не выбрана'
            self.release_values[key].setText(QDateTime.fromString(plan[key],Qt.ISODate).toLocalTime().toString('dd.MM.yyyy · HH:mm') if plan and plan[key] else missing if plan else 'Не задано')
        dates=[]
        if plan:
            for key,title in (('websiteAt','Сайт'),('launcherAt','Лаунчер'),('serverAt','Открытие сервера')):
                if plan[key]:dates.append(title+'\n'+QDateTime.fromString(plan[key],Qt.ISODate).toLocalTime().toString('dd.MM.yyyy · HH:mm'))
        self.rail_dates.setText('\n\n'.join(dates)+'\nМестное время' if dates else 'Даты — по согласованию\nс NEXUS.')
        self.reference.setText(f"Заявка: {item['id']}\nВерсия: {item['revision']}" if item else 'После сохранения здесь появится номер заявки.')
        hint='Дождитесь ответа кабинета.' if self.busy else 'Сначала проверьте сохранённые данные.' if self.workspace.unknown else 'Заявка отправлена. Для изменений её нужно отозвать.' if item and item['state']=='SUBMITTED' else 'Сначала сохраните черновик.' if not item else 'Сохраните правки перед отправкой на проверку.' if self.dirty else 'Для проверки заполните все обязательные поля.' if not complete else 'Подтвердите права на материалы перед отправкой.' if not self.rights.isChecked() else 'Версия готова к отправке на ручную проверку.'
        self.submission_hint.setText(hint)

    def populate(self,content):
        self.content=deepcopy(content)
        for key,field in self.fields.items():
            field.blockSignals(True)
            if isinstance(field,QPlainTextEdit):field.setPlainText(content[key])
            else:field.setText(content[key])
            field.blockSignals(False)
        self.plan.setText('Даты указаны в местном времени.' if content.get('releasePlan') else 'Настройте «План выпуска» проекта и нажмите «Взять из проекта».')
        self.dirty=False
        self.rights.setChecked(False)

    def current_content(self):
        value=deepcopy(self.content)
        for key,field in self.fields.items():value[key]=field.toPlainText() if isinstance(field,QPlainTextEdit) else field.text()
        return validate_page_content(value)

    def project_content(self):
        w=self.workspace
        return page_from_project(w.service.load(w.identifier),w.service.instances.load(w.identifier))

    def use_project(self):
        if QMessageBox.question(self,'Данные проекта','Заменить поля формы и план данными локального проекта? На сайте они изменятся только после «Сохранить черновик».')!=QMessageBox.Yes:return
        try:self.populate(self.project_content());self.mark_dirty()
        except ValueError:self.status.setText('Проверьте длину данных проекта: название до 80, описание до 2400 символов. Существующие данные не изменены.')

    def load(self):
        if self.dirty and QMessageBox.question(self,'Несохранённые поля','Отменить изменения формы и прочитать сохранённую версию с сайта?')!=QMessageBox.Yes:return
        self.run('load',self.workspace.load)

    def attach_existing(self):
        identifier=self.existing.currentData()
        if not identifier or self.busy:return
        if QMessageBox.question(self,'Существующая заявка','Связать проект с выбранной заявкой и загрузить её поля? Локальные файлы сборки не отправляются. Несохранённые поля формы будут заменены.')!=QMessageBox.Yes:return
        self.run('attach',lambda:self.workspace.attach(identifier))

    def run(self,action,work):
        if self.busy:return
        self.busy=True;self.controls();self.status.setText('Получаем ответ кабинета…')
        def worker():
            try:self.finished_operation.emit(action,work(),None)
            except Exception as error:self.finished_operation.emit(action,None,error)
        threading.Thread(target=worker,daemon=True).start()

    def write(self,action):
        if self.busy:return
        try:
            content=self.current_content() if action=='save' else None
            if action=='submit':
                validate_page_content(self.workspace.item['content'],True)
                if self.dirty or not self.rights.isChecked():raise ValueError('Сохраните поля и подтвердите права')
            if action in ('submit','reopen') and QMessageBox.question(self,'Подтвердить действие','Отправить сохранённую версию на ручную проверку NEXUS? Это не публикация.' if action=='submit' else 'Отозвать заявку для редактирования? Назначенный выпуск этой версии перестанет показываться.')!=QMessageBox.Yes:return
            rights=self.rights.isChecked()
            self.run(action,lambda:self.workspace.write(action,content,rights))
        except (ValueError,TypeError):self.status.setText('Проверьте обязательные поля, длину, адрес сайта и подтверждение прав. Сначала сохраните черновик.')

    def complete(self,action,result,error):
        self.busy=False
        if error:
            status=getattr(error,'http_status',None)
            identity_changed=isinstance(error,SessionRejected)
            if status in (401,403) or identity_changed or action=='load':
                self.content=None
                for field in self.fields.values():field.blockSignals(True);field.clear();field.blockSignals(False)
                self.plan.clear()
                self.rights.setChecked(False)
                self.dirty=False
                self.existing.blockSignals(True);self.existing.clear();self.existing.addItem('Обновите данные аккаунта',None);self.existing.blockSignals(False)
                self.association_toggle.setChecked(False)
            self.status.setText('Аккаунт изменён. Закройте окно и войдите заново.' if identity_changed else 'Нет доступа: обновите профиль и выберите «Создатель серверов» в кабинете сайта.' if status in (401,403) else 'Проверьте поля, общий размер заявки и привязку проекта. Локальная проверка отклонила действие.' if isinstance(error,ValueError) else 'Результат не подтверждён. Проверьте сохранённые данные перед повтором. При ошибке чтения проверьте аккаунт и привязку проекта.')
        else:
            if action=='load':
                self.existing.blockSignals(True)
                self.existing.clear();self.existing.addItem('Новая заявка для этого проекта',None)
                for item in self.workspace.available:self.existing.addItem(item['content']['name'] or 'Без названия',item['id'])
                if self.workspace.link:self.existing.setCurrentIndex(max(0,self.existing.findData(self.workspace.link['id'])))
                self.existing.blockSignals(False)
            if self.workspace.link:self.association_toggle.setChecked(False)
            try:self.populate(result['content'] if result else self.project_content())
            except ValueError:self.content=None;self.status.setText('Данные проекта превышают лимиты страницы. Исправьте их в проекте и обновите данные.');self.controls();return
            item=self.workspace.item
            self.status.setText(f"Версия {item['revision']} · "+('заявка на проверке' if item['state']=='SUBMITTED' else 'черновик сохранён в кабинете')+(' · '+{'APPROVED':'одобрена','CHANGES_REQUESTED':'нужны правки','REJECTED':'отклонена'}[item['review']['decision']] if item.get('review') else '') if item else 'Сохраните черновик, когда заполните страницу. Он останется личным до отправки на проверку.')
            if self.content.get('mode','blocks')!='blocks':self.status.setText(self.status.text()+' · Этот тип страницы редактируется в кабинете сайта.')
        self.controls()

    def reject(self):
        if self.busy:return
        if self.dirty and QMessageBox.question(self,'Несохранённые поля','Закрыть форму без сохранения изменений?')!=QMessageBox.Yes:return
        super().reject()

    def closeEvent(self,event):
        if self.busy:event.ignore();return
        if self.dirty and QMessageBox.question(self,'Несохранённые поля','Закрыть форму без сохранения изменений?')!=QMessageBox.Yes:event.ignore();return
        event.accept()
