"""Native support surface shared by Qt and DesignHost. No JS credentials."""
import threading
import uuid
from PySide6.QtCore import QObject, QSettings, QTimer, Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QTextEdit, QLineEdit, QPushButton, QSplitter
from nexus_launcher.nexus_account import AccountError, SessionRejected

def status_label(value):
    return {'open':'Открыто','waiting_for_staff':'Ожидает поддержки','waiting_for_user':'Ожидает вашего ответа','closed':'Закрыто',
        'pending':'В очереди доставки','leased':'В очереди доставки','dispatching':'Доставляется','delivered':'Доставлено поддержке',
        'uncertain':'Доставка проверяется сотрудником','failed':'Доставка требует внимания сотрудника'}.get(value, 'Сохранено')


class SupportSignals(QObject):
    completed = Signal(object, object)


class SupportPage(QWidget):
    def __init__(self, launcher):
        super().__init__()
        self.launcher, self.busy, self.generation = launcher, False, 0
        self.ticket, self.messages, self.cursor = None, [], 0
        self.pending = None
        self.owner = ''
        self.settings = QSettings('NEXUS', 'Support')
        self.signals = SupportSignals(self)
        self.signals.completed.connect(self.completed, Qt.ConnectionType.QueuedConnection)
        self.timer = QTimer(self); self.timer.setInterval(5000); self.timer.timeout.connect(self.refresh)
        root = QVBoxLayout(self)
        title = QLabel('ПОДДЕРЖКА NEXUS'); title.setObjectName('pageTitle'); root.addWidget(title)
        self.state = QLabel('История обращений сохраняется в аккаунте NEXUS.'); self.state.setWordWrap(True); root.addWidget(self.state)
        split = QSplitter(); root.addWidget(split, 1)
        self.tickets = QListWidget(); self.tickets.setAccessibleName('Обращения'); self.tickets.setMinimumWidth(220); self.tickets.setWordWrap(True); split.addWidget(self.tickets)
        self.tickets.currentRowChanged.connect(self.select)
        panel = QWidget(); right = QVBoxLayout(panel); split.addWidget(panel); split.setStretchFactor(0, 0); split.setStretchFactor(1, 1); split.setSizes([260, 740])
        self.history = QTextEdit(); self.history.setReadOnly(True); self.history.setAccessibleName('Переписка'); right.addWidget(self.history, 1)
        self.subject = QLineEdit(); self.subject.setPlaceholderText('Тема нового обращения'); self.subject.setMaxLength(160); self.subject.setAccessibleName('Тема обращения'); right.addWidget(self.subject)
        self.text = QTextEdit(); self.text.setPlaceholderText('Сообщение — до 4000 символов'); self.text.setAccessibleName('Текст сообщения'); self.text.setMaximumHeight(130); right.addWidget(self.text)
        controls = QHBoxLayout(); right.addLayout(controls)
        self.create = QPushButton('Новое обращение'); self.create.clicked.connect(lambda: self.send(True)); controls.addWidget(self.create)
        self.send_button = QPushButton('Отправить'); self.send_button.clicked.connect(lambda: self.send(False)); controls.addWidget(self.send_button)
        self.close_button = QPushButton('Закрыть / открыть'); self.close_button.clicked.connect(self.change_status); controls.addWidget(self.close_button)
        retry = QPushButton('Обновить список'); retry.clicked.connect(lambda: self.request('tickets')); controls.addWidget(retry)
        self.more_button = QPushButton('Ещё обращения'); self.more_button.clicked.connect(self.more); root.addWidget(self.more_button); self.more_button.hide()
        self.next_list = None
        self.rows = []

    def showEvent(self, event):
        super().showEvent(event); self.timer.start(); self.refresh()

    def hideEvent(self, event):
        self.timer.stop(); self.generation += 1; super().hideEvent(event)

    def account(self):
        profile = self.launcher.account_profile
        return profile.user_id if profile else ''

    def request(self, path, payload=None, idem=None):
        if self.busy:
            return
        account = self.account()
        if account != self.owner:
            self.owner = account; self.ticket = None; self.messages = []; self.cursor = 0; self.pending = None; self.rows = []; self.next_list = None; self.history.clear(); self.tickets.clear(); self.text.clear(); self.subject.clear()
            if payload is not None:
                self.state.setText('Аккаунт изменился. Черновик очищен; отправка отменена.'); return
            if path != 'tickets':
                path, payload, idem = 'tickets', None, None
        if not account:
            self.history.clear(); self.tickets.clear(); self.state.setText('Войдите в аккаунт NEXUS. Minecraft-ник для поддержки не нужен.'); return
        client = self.launcher.account_client
        token = client.support_session(account)
        if not token:
            self.ticket = None; self.messages = []; self.cursor = 0; self.pending = None; self.rows = []; self.next_list = None
            self.history.clear(); self.tickets.clear(); self.text.clear(); self.subject.clear()
            self.state.setText("Войдите в аккаунт NEXUS."); return
        generation = self.generation
        self.busy = True; self.state.setText('Загрузка…')
        for button in (self.create, self.send_button, self.close_button): button.setEnabled(False)
        def work():
            try:
                if generation != self.generation or account != self.account() or client is not self.launcher.account_client:
                    raise SessionRejected('Сессия изменилась. Отправка отменена.', code='SESSION_CHANGED')
                # Verify the captured credential's owner without blocking the UI.
                identity, _ = client._request('/api/launcher/profile', token=token)
                if identity.get('user', {}).get('id') != account or generation != self.generation or account != self.account():
                    raise SessionRejected('Сессия изменилась. Отправка отменена.', code='SESSION_CHANGED')
                result, _ = client._request('/api/v1/support/' + path, method='POST' if payload is not None else 'GET', payload=payload, token=token, idempotency_key=idem)
                output = (path, result, account, generation, payload is not None)
                error = None
            except AccountError as exc:
                output = (path, None, account, generation, payload is not None)
                error = 'VERSION_CONFLICT' if exc.code in ('VERSION_CONFLICT', 'IDEMPOTENCY_CONFLICT', 'INVALID_VERSION') else 'SESSION_CHANGED' if exc.code == 'SESSION_CHANGED' else 'TICKET_NOT_FOUND' if exc.code == 'TICKET_NOT_FOUND' else ('Сессия истекла. Войдите снова.' if isinstance(exc, SessionRejected) else 'Сервис временно недоступен. Повторите запрос; сообщение не потеряется при повторе.')
            except Exception:
                output = (path, None, account, generation, payload is not None); error = 'Не удалось загрузить поддержку.'
            try: self.signals.completed.emit(output, error)
            except RuntimeError: pass
        threading.Thread(target=work, daemon=True).start()

    def completed(self, output, error):
        path, data, account, generation, mutation = output
        self.busy = False
        for button in (self.create, self.send_button, self.close_button): button.setEnabled(True)
        if account != self.account() or error == 'SESSION_CHANGED':
            self.owner = ''; self.ticket = None; self.messages = []; self.cursor = 0; self.pending = None; self.rows = []; self.next_list = None
            self.history.clear(); self.tickets.clear(); self.text.clear(); self.subject.clear()
            return
        if generation != self.generation:
            return
        if error:
            if error == 'VERSION_CONFLICT':
                self.pending = None; self.state.setText('Обращение изменилось. Обновите историю и подтвердите отправку снова.'); return
            if error == 'TICKET_NOT_FOUND':
                self.ticket = None; self.messages = []; self.cursor = 0; self.history.clear(); self.settings.remove(account); QTimer.singleShot(0, self.refresh); return
            self.state.setText(error); self.timer.setInterval(min(60000, self.timer.interval() * 2)); return
        self.timer.setInterval(5000)
        if mutation:
            if path == 'tickets' or path.endswith('/messages'): self.pending = None; self.text.clear()
            if path == 'tickets':
                self.ticket = data; self.settings.setValue(account, data['id']); self.cursor = 0; self.messages = []
                self.rows.insert(0, data); self.tickets.blockSignals(True); self.tickets.insertItem(0, f"{data['subject']}\n{status_label(data['status'])}"); self.tickets.setCurrentRow(0); self.tickets.blockSignals(False)
            self.state.setText('Сохранено в NEXUS. Доставка администрации может занять время.'); QTimer.singleShot(0, self.refresh); return
        if path == 'tickets' or path.startswith('tickets?cursor='):
            selected = self.ticket['id'] if self.ticket else str(self.settings.value(account, ''))
            self.rows = self.rows + data['tickets'] if path.startswith('tickets?cursor=') else data['tickets']; self.next_list = data.get('nextCursor'); self.more_button.setVisible(bool(self.next_list)); self.tickets.blockSignals(True); self.tickets.clear()
            for row in self.rows: self.tickets.addItem(f"{row['subject']}\n{status_label(row['status'])}")
            self.tickets.blockSignals(False)
            index = next((i for i,r in enumerate(self.rows) if r['id'] == selected), -1 if selected else (0 if self.rows else -1))
            if selected and index == -1 and len(selected) == 64:
                self.ticket = {'id': selected}; self.cursor = 0; self.messages = []; QTimer.singleShot(0, self.refresh); return
            self.state.setText('Нет обращений. Опишите вопрос справа.' if index < 0 else 'Выберите обращение.')
            if index >= 0:
                self.tickets.blockSignals(True); self.tickets.setCurrentRow(index); self.tickets.blockSignals(False)
                if not self.ticket or self.ticket['id'] != self.rows[index]['id']: self.select(index)
        else:
            self.ticket = data['ticket']; self.cursor = data['nextCursor']; seen = {m['id'] for m in self.messages}; self.messages.extend(m for m in data['messages'] if m['id'] not in seen)
            deliveries = {row['id']: row['delivery'] for row in data.get('deliveries', [])}
            for message in self.messages:
                if message['id'] in deliveries: message['delivery'] = deliveries[message['id']]
            self.history.setPlainText('\n\n'.join(f"{'Поддержка' if m['source']=='telegram' else 'Вы'} · {status_label(m.get('delivery'))}\n{m['body']}" for m in self.messages))
            self.state.setText('Статус: ' + status_label(self.ticket['status']))
            for index,row in enumerate(self.rows):
                if row['id'] == self.ticket['id']:
                    self.rows[index] = self.ticket; self.tickets.item(index).setText(f"{self.ticket['subject']}\n{status_label(self.ticket['status'])}")
            if data['hasMore']: QTimer.singleShot(0, self.refresh)

    def select(self, index):
        if self.busy or not 0 <= index < len(self.rows): return
        self.ticket = self.rows[index]; self.messages = []; self.cursor = 0
        self.settings.setValue(self.account(), self.ticket['id']); self.refresh()

    def refresh(self):
        if not self.isVisible() or self.busy: return
        self.request(f"tickets/{self.ticket['id']}/messages?after={self.cursor}" if self.ticket else 'tickets')

    def more(self):
        if self.next_list and not self.busy:
            from urllib.parse import quote
            self.request('tickets?cursor=' + quote(str(self.next_list), safe=''))

    def send(self, create):
        message = self.text.toPlainText().strip()
        if not message or len(message.encode('utf-16-le')) // 2 > 4000 or (create and not self.subject.text().strip()):
            self.state.setText('Введите тему и сообщение до 4000 символов.'); return
        if not create and not self.ticket: self.state.setText('Сначала выберите обращение.'); return
        path = 'tickets' if create else f"tickets/{self.ticket['id']}/messages"
        payload = {'subject': self.subject.text().strip(), 'category': 'general', 'text': message} if create else {'text': message, 'version': self.pending[1].get('version') if self.pending else self.ticket.get('version')}
        signature = (path, payload)
        if self.pending and self.pending[:2] != signature:
            self.state.setText('Сначала повторите предыдущую отправку без изменения текста.'); return
        if not self.pending: self.pending = (*signature, str(uuid.uuid4()))
        self.request(path, payload, self.pending[2])

    def change_status(self):
        if self.ticket:
            action = 'reopen' if self.ticket['status'] == 'closed' else 'close'
            self.request(f"tickets/{self.ticket['id']}/{action}", {'version': self.ticket['version']})
