"""Registration against the website's existing account database and email checks."""
import re
import threading
from http.cookies import SimpleCookie
from urllib.parse import urlencode, urlsplit

from PySide6.QtCore import QObject, Signal, Slot, Qt, QRegularExpression, QTimer, QRect
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget, QStackedWidget, QSizePolicy

from nexus_launcher.nexus_account import AccountError, NexusAccountClient, ProtocolError
from nexus_launcher.secure_http import origin
from nexus_launcher.registration_errors import registration_error
from .theme_tokens import TOKENS
from .presentation_style import stylesheet
from nexus_launcher.password_visibility import PasswordVisibilityButton


def valid_registration_email(email):
    """Check address syntax locally; never probe DNS or mail delivery."""
    if not isinstance(email, str) or len(email) > 254 or email.count('@') != 1:
        return False
    local, domain = email.split('@')
    if (not local or len(local) > 64 or local.startswith('.') or local.endswith('.')
            or '..' in local or re.search(r'[\s\x00-\x1f\x7f@]', local)):
        return False
    try:
        domain = domain.encode('idna').decode('ascii')
    except UnicodeError:
        return False
    labels = domain.split('.')
    return len(labels) >= 2 and all(
        re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
        for label in labels
    )


class WebsiteRegistrationClient(NexusAccountClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parts = urlsplit(self.base_url)
        if parts.path not in ('', '/') or parts.query:
            raise AccountError('Некорректный адрес сервера регистрации.')
        self._registration_base = self.base_url
        self._registration_origin = origin(self.base_url)
        self._registration_session = None

    def clear_registration_session(self):
        self._registration_session = None

    def _response_headers(self, path, result, headers):
        if path != '/api/auth/register' or result.get('ok') is not True:
            return
        self._registration_session = None
        values = headers.get_all('Set-Cookie', [])
        for value in values:
            cookie = SimpleCookie()
            try:
                cookie.load(value)
            except Exception:
                continue
            session = cookie.get('nexus_session')
            if (session and re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', session.value)
                    and session['secure'] and session['httponly'] and session['path'] == '/'
                    and not session['domain'] and session['samesite'].lower() == 'lax'
                    and session['max-age'].isdigit() and int(session['max-age']) > 0):
                self._registration_session = session.value

    def _additional_headers(self, path, method):
        if urlsplit(path).path != '/api/profile/setup':
            return {}
        if self.base_url != self._registration_base or origin(self.base_url) != self._registration_origin or not self._registration_session:
            raise AccountError('Аккаунт создан. Для настройки ника нужна действующая сессия; войдите на сайте NEXUS.')
        scheme, host, _ = self._registration_origin
        return {'Cookie': 'nexus_session=' + self._registration_session, 'Origin': f'{scheme}://{host}'}

    @staticmethod
    def _nickname(nick):
        if not isinstance(nick, str) or not re.fullmatch(r'[A-Za-z0-9_]{3,16}', nick.strip()):
            raise AccountError('Ник: 3–16 латинских букв, цифр или _.')
        return nick.strip()

    def nickname_available(self, nick):
        nick = self._nickname(nick)
        result, _ = self._request('/api/profile/setup?' + urlencode({'nick': nick}))
        if type(result.get('available')) is not bool:
            raise ProtocolError('Не удалось подтвердить доступность ника.')
        return result['available']

    def complete_profile(self, nick):
        nick = self._nickname(nick)
        # Recover a lost POST response by reading committed state before any retry.
        current, _ = self._request('/api/profile/setup')
        if current.get('profileCompleted') is True:
            if isinstance(current.get('minecraftNick'), str) and current['minecraftNick'].lower() == nick.lower():
                return current['minecraftNick']
            raise AccountError('Игровой профиль уже настроен с другим ником. Войдите в аккаунт.')
        if current.get('profileCompleted') is not False:
            raise ProtocolError('Не удалось проверить состояние игрового профиля.')
        result, _ = self._request('/api/profile/setup', method='POST', payload={'minecraftNick': nick})
        if result.get('ok') is not True or result.get('profileCompleted') is not True or result.get('minecraftNick') != nick:
            raise ProtocolError('Сохранение ника не подтверждено. Повторная попытка сначала проверит профиль.')
        return nick

    def request_code(self, email, password):
        email = email.strip().lower()
        if not valid_registration_email(email):
            raise AccountError("Введите корректную электронную почту.")
        result, _ = self._request("/api/auth/email/request-code", method="POST",
                                  payload={"email": email, "password": password, "deviceId": self._device_id()})
        challenge = result.get("challengeId")
        if result.get("ok") is not True or not isinstance(challenge, str) or not 1 <= len(challenge) <= 128:
            raise ProtocolError("Сайт не вернул подтверждение отправки кода.")
        return challenge

    def register(self, email, nick, password, challenge, code, display_name=None):
        nick = self._nickname(nick)
        if not 8 <= len(password) <= 1024:
            raise AccountError("Пароль: минимум 8 символов.")
        if not challenge or not re.fullmatch(r"[0-9]{6}", code):
            raise AccountError("Введите шестизначный код из письма.")
        self.clear_registration_session()
        result, _ = self._request("/api/auth/register", method="POST", payload={
            "email": email.strip().lower(), "password": password,
            "minecraftNick": nick,
            "challengeId": challenge, "verificationCode": code, "deviceId": self._device_id(),
        })
        if result.get("ok") is not True:
            raise ProtocolError("Сайт не подтвердил создание аккаунта. Проверьте вход перед повторной регистрацией.")
        # The deployed server completes the profile in this operation. Newer
        # servers may explicitly defer it; never infer completion from our input.
        user = result.get("user")
        if isinstance(user, dict) and user.get("profileCompleted") is not False:
            saved = user.get("minecraftNick")
            if isinstance(saved, str) and re.fullmatch(r"[A-Za-z0-9_]{3,16}", saved) and saved.lower() == nick.lower():
                return saved
        return None


class RegistrationBridge(QObject):
    done = Signal(str, str, str)


class CodeDigit(QLineEdit):
    def __init__(self, owner, index):
        super().__init__(owner)
        self.owner, self.index = owner, index
        self.setMaxLength(6)
        self.setValidator(QRegularExpressionValidator(QRegularExpression('[0-9]{0,6}'), self))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedSize(46, 60)
        self.setAccessibleName(f'Цифра кода {index + 1} из 6')
        self.textEdited.connect(lambda text: owner.distribute(index, text))

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.selectAll()

    def keyPressEvent(self, event):
        if not self.isReadOnly() and event.key() == Qt.Key.Key_Backspace and not self.text() and self.index:
            previous = self.owner.digits[self.index - 1]
            previous.clear()
            previous.setFocus()
            return
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            index = self.index + (-1 if event.key() == Qt.Key.Key_Left else 1)
            if 0 <= index < 6:
                self.owner.digits[index].setFocus()
                return
        super().keyPressEvent(event)


class VerificationCode(QWidget):
    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self.digits = [CodeDigit(self, index) for index in range(6)]
        for digit in self.digits:
            layout.addWidget(digit)
        self.setFocusProxy(self.digits[0])

    def distribute(self, index, text):
        if not text:
            return
        start = 0 if len(text) == 6 else index
        for offset, digit in enumerate(text[:6 - start]):
            self.digits[start + offset].setText(digit)
        target = min(start + len(text), 5)
        self.digits[target].setFocus()

    def text(self):
        return ''.join(digit.text() for digit in self.digits)

    def setText(self, text):
        if not re.fullmatch('[0-9]{0,6}', text):
            return
        self.clear()
        for index, char in enumerate(text):
            self.digits[index].setText(char)

    def clear(self):
        for digit in self.digits:
            digit.clear()

    def setReadOnly(self, locked):
        for digit in self.digits:
            digit.setReadOnly(locked)

    def isReadOnly(self):
        return all(digit.isReadOnly() for digit in self.digits)


from nexus_launcher.themed_dialog import NexusDialog


class RegistrationDialog(NexusDialog):
    profile_saved = Signal(str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.challenge = ""
        self.busy = False
        self.completed = False
        self.profile_completed = False
        self.registered_email = ""
        self.bridge = RegistrationBridge(self)
        self.bridge.done.connect(self._completed, Qt.ConnectionType.QueuedConnection)
        self.setWindowTitle("Регистрация NEXUS")
        self.setObjectName("registrationDialog")
        self.setStyleSheet(stylesheet() + f"""
            QDialog#registrationDialog {{ background:{TOKENS['background']}; }}
            QLabel#registrationBrand {{ color:{TOKENS['accent']}; font-size:18px; font-weight:700; }}
            QLabel#registrationCaption {{ color:{TOKENS['muted']}; font-size:12px; }}
            QLabel#registrationTitle {{ font-family:'Bahnschrift','Segoe UI'; font-size:28px; font-weight:650; }}
            QLabel#registrationHint {{ color:{TOKENS['muted']}; font-size:14px; }}
            QWidget#registrationCode {{ background:{TOKENS['sidebar']}; border:1px solid {TOKENS['border']}; border-radius:12px; }}
            QWidget#registrationCode QLabel {{ border:0; background:transparent; }}
            QWidget#verificationCode QLineEdit {{ font-family:'Consolas'; font-size:26px; font-weight:600; padding:0; }}
            QPushButton#passwordVisibility, QPushButton#registrationEdit {{ background:transparent; color:{TOKENS['accent']}; text-align:left; padding:8px 0; }}
        """)
        self.resize(520, 640)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(14)
        brand = QLabel("NEXUS")
        brand.setObjectName("registrationBrand")
        root.addWidget(brand)
        caption = QLabel("ForceCore Production")
        caption.setObjectName("registrationCaption")
        root.addWidget(caption)
        title = QLabel("Создать аккаунт")
        self.title = title
        title.setObjectName("registrationTitle")
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        root.addWidget(title)
        self.hint = QLabel("Один аккаунт для сайта и лаунчера. Выберите ник и подтвердите почту.")
        self.hint.setObjectName("registrationHint")
        self.hint.setWordWrap(True)
        self.hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        root.addWidget(self.hint)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setVerticalSpacing(4)
        self.steps = QStackedWidget()
        self.credentials_page = QWidget()
        credentials_layout = QVBoxLayout(self.credentials_page)
        credentials_layout.setContentsMargins(0, 0, 0, 0)
        self.email = QLineEdit()
        self.email.setMaxLength(254)
        self.email.setPlaceholderText("you@example.com")
        self.nick = QLineEdit()
        self.nick.setMaxLength(16)
        self.display_name = QLineEdit()
        self.display_name.setMaxLength(64)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setMaxLength(1024)
        self.password.setPlaceholderText("Минимум 8 символов")
        self.nick.setPlaceholderText("3–16 латинских букв, цифр или _")
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm.setMaxLength(1024)
        self.nick.hide()
        self.display_name.hide()
        self.registration_nick = QLineEdit()
        self.registration_nick.setMaxLength(16)
        self.registration_nick.setPlaceholderText("3–16 латинских букв, цифр или _")
        self.registration_nick.textChanged.connect(self.nick.setText)
        for text, field in (("Электронная почта", self.email), ("Ник Minecraft / логин NEXUS", self.registration_nick), ("Пароль", self.password), ("Повторите пароль", self.confirm)):
            label = QLabel(text)
            label.setBuddy(field)
            field.setAccessibleName(text)
            # Keep text and themed padding visible in embedded form layouts.
            field.setMinimumHeight(36)
            form.addRow(label, field)
        credentials_layout.addLayout(form)
        self.password_visibility = PasswordVisibilityButton(self.password)
        self.confirm_visibility = PasswordVisibilityButton(self.confirm)
        self.steps.addWidget(self.credentials_page)
        self.code_box = QWidget()
        self.code_box.setObjectName("registrationCode")
        code_layout = QVBoxLayout(self.code_box)
        code_layout.setContentsMargins(16, 14, 16, 14)
        self.code = VerificationCode()
        self.code.setObjectName("verificationCode")
        self.code.setAccessibleName("Шестизначный код из письма")
        code_label = QLabel("Код из письма · действует 10 минут")
        code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        code_label.setBuddy(self.code)
        code_layout.addWidget(code_label)
        code_layout.addStretch()
        code_layout.addWidget(self.code, 0, Qt.AlignmentFlag.AlignCenter)
        code_layout.addStretch()
        self.steps.addWidget(self.code_box)
        self.nickname_page = QWidget()
        nickname_layout = QVBoxLayout(self.nickname_page)
        nickname_layout.setContentsMargins(0, 0, 0, 0)
        nickname_label = QLabel('Ник Minecraft / логин NEXUS')
        nickname_label.setBuddy(self.nick)
        self.nick.setAccessibleName('Ник Minecraft')
        self.nick.setPlaceholderText('Например, Isus_Hrestos')
        self.nick.setMinimumHeight(44)
        nickname_layout.addWidget(nickname_label)
        nickname_layout.addWidget(self.nick)
        nickname_help = QLabel('3–16 латинских букв, цифр или _. Ник должен быть свободен в NEXUS.')
        nickname_help.setWordWrap(True)
        nickname_help.setObjectName('registrationHint')
        nickname_layout.addWidget(nickname_help)
        self.check_nick = QPushButton('Проверить ник')
        self.check_nick.clicked.connect(self._check_nickname)
        nickname_layout.addWidget(self.check_nick, 0, Qt.AlignmentFlag.AlignLeft)
        self.nickname_status = QLabel()
        self.nickname_status.setWordWrap(True)
        nickname_layout.addWidget(self.nickname_status)
        nickname_layout.addStretch()
        self.nick.textChanged.connect(self.nickname_status.clear)
        self.steps.addWidget(self.nickname_page)
        root.addWidget(self.steps, 1)
        self.error = QLabel()
        self.error.setTextFormat(Qt.TextFormat.PlainText)
        self.error.setWordWrap(True)
        self.error.setMinimumHeight(44)
        self.error.setStyleSheet(f"color:{TOKENS['danger']};")
        root.addWidget(self.error)
        self.edit = QPushButton("Не пришло письмо? Запросить снова")
        self.edit.setObjectName("registrationEdit")
        self.edit.clicked.connect(self._resend)
        self.edit.hide()
        root.addWidget(self.edit)
        actions = QHBoxLayout()
        cancel = QPushButton("Отмена")
        self.cancel = cancel
        cancel.clicked.connect(self._back)
        self.submit = QPushButton("Получить код")
        self.submit.setObjectName("primaryAction")
        self.submit.setDefault(True)
        self.submit.setMinimumWidth(180)
        self.submit.clicked.connect(self._submit)
        actions.addWidget(cancel)
        actions.addWidget(self.submit)
        root.addLayout(actions)
        self.email.setFocus()

    def _fit_copy(self):
        # Embedded QDialogs can otherwise shrink wrapped QLabel text to one line.
        for label in (self.title, self.hint):
            label.ensurePolished()
            width = max(1, self.width() - self.layout().contentsMargins().left() - self.layout().contentsMargins().right())
            # QLabel.heightForWidth is constrained by its existing minimum size.
            # Measure text independently to avoid repeated +padding feedback.
            height = label.fontMetrics().boundingRect(QRect(0, 0, width, 10000), Qt.TextFlag.TextWordWrap, label.text()).height() + 4
            if label.minimumHeight() != height or label.maximumHeight() != height:
                label.setFixedHeight(height)
        if self.profile_completed:
            self.layout().setAlignment(Qt.AlignmentFlag.AlignTop)
            self.layout().activate()
            height = self.layout().minimumSize().height() + 8
            if self.maximumHeight() != height:
                self.setMaximumHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'hint'):
            self._fit_copy()

    def _reset(self):
        if self.busy:
            return
        self.challenge = ""
        self.code.clear()
        self.steps.setCurrentWidget(self.credentials_page)
        self.title.setText("Создать аккаунт")
        self.title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.hint.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.edit.hide()
        self.submit.setText("Получить код")
        self.cancel.setText("Отмена")
        self.hint.setText("Новый код можно запросить не раньше чем через минуту после предыдущего.")
        self._lock_fields(False)
        self.error.clear()
        self.email.setFocus()

    def _lock_fields(self, locked):
        for field in (self.email, self.registration_nick, self.nick, self.display_name, self.password, self.confirm):
            field.setReadOnly(locked)

    def _back(self):
        if self.completed and not self.busy:
            self.accept()  # Account remains valid; gameplay still requires a profile.
        elif self.challenge and not self.busy:
            self._reset()
        else:
            self.reject()

    def _resend(self):
        if self.challenge and not self.busy:
            self._submit(request_code=True)

    def _submit(self, request_code=False):
        if self.busy:
            return
        if self.completed:
            if self.profile_completed:
                self.accept()
            else:
                self._profile_request(False)
            return
        email, nick, password = self.email.text().strip().lower(), self.nick.text().strip(), self.password.text()
        if not valid_registration_email(email):
            self.error.setText("Введите корректную почту.")
            self.email.setFocus()
            return
        if not re.fullmatch(r'[A-Za-z0-9_]{3,16}', nick):
            self.error.setText('Ник: 3–16 латинских букв, цифр или _.')
            self.registration_nick.setFocus()
            return
        if len(password) < 8 or not password.strip():
            self.error.setText("Пароль слишком короткий! Нужно минимум 8 символов, не только пробелы.")
            self.password.setFocus()
            return
        if len(password) > 1024:
            self.error.setText("Пароль слишком длинный! Максимум 1024 символа.")
            self.password.setFocus()
            return
        if password != self.confirm.text():
            self.error.setText("Пароли не совпадают. Проверьте повтор пароля.")
            self.confirm.setFocus()
            return
        code = self.code.text().strip()
        if self.challenge and not request_code and not re.fullmatch(r"[0-9]{6}", code):
            self.error.setText("Введите 6 цифр из письма.")
            self.code.setFocus()
            return
        display_name = self.display_name.text().strip() or nick
        action, challenge = ("register" if self.challenge and not request_code else "code"), self.challenge
        self.busy = True
        self.submit.setEnabled(False)
        self.edit.setEnabled(False)
        self._lock_fields(True)
        self.code.setReadOnly(True)
        self.error.setText("Отправляем запрос…")

        def work():
            try:
                result = self.client.request_code(email, password) if action == "code" else self.client.register(email, nick, password, challenge, code, display_name)
                error = ""
            except AccountError as exc:
                result, error = "", registration_error(exc, action)
            except Exception:
                result, error = "", "Не удалось завершить запрос. Проверьте вход на сайте перед повтором."
            try:
                self.bridge.done.emit(action, result or "", error)
            except RuntimeError:
                pass  # Application shutdown; never replay a registration request.

        threading.Thread(target=work, daemon=True).start()

    def _check_nickname(self):
        self._profile_request(True)

    def _profile_request(self, check):
        if self.busy or not self.completed or self.profile_completed:
            return
        nick = self.nick.text().strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{3,16}', nick):
            self.error.setText('Ник: 3–16 латинских букв, цифр или _.')
            self.nick.setFocus()
            return
        self.busy = True
        self.submit.setEnabled(False)
        self.check_nick.setEnabled(False)
        self.nick.setReadOnly(True)
        self.error.setText('Проверяем ник…' if check else 'Сохраняем игровой профиль…')
        action = 'availability:' + nick if check else 'profile'
        def work():
            try:
                result = ('available' if self.client.nickname_available(nick) else 'taken') if check else self.client.complete_profile(nick)
                error = ''
            except AccountError as exc:
                result, error = '', registration_error(exc, 'availability' if check else 'profile')
            except Exception:
                result, error = '', 'Не удалось настроить ник. Аккаунт уже создан; повторять регистрацию не нужно.'
            try:
                self.bridge.done.emit(action, result or '', error)
            except RuntimeError:
                pass
        threading.Thread(target=work, daemon=True).start()

    @Slot(str, str, str)
    def _completed(self, action, result, error):
        QTimer.singleShot(0, self._fit_copy)
        self.busy = False
        self.submit.setEnabled(True)
        self.edit.setEnabled(True)
        self.code.setReadOnly(False)
        self._lock_fields(bool(self.challenge))
        self.error.setText(error)
        if action == 'profile' or action.startswith('availability:'):
            self.check_nick.setEnabled(True)
            self.nick.setReadOnly(False)
            if error:
                return
            if action.startswith('availability:'):
                if self.nick.text().strip() == action.split(':', 1)[1]:
                    self.nickname_status.setText('Ник свободен в NEXUS.' if result == 'available' else 'Ник уже занят в NEXUS. Выберите другой.')
                return
            self.profile_completed = True
            self.steps.hide()
            self.cancel.hide()
            self.title.setText('Готово, ' + result + '!')
            self.hint.setText('Твой ник: ' + result + '. Теперь войди с этим ником или почтой и паролем.')
            self.submit.setText('Продолжить')
            self.profile_saved.emit(result)
            return
        if error:
            return
        if action == "code":
            self.challenge = result
            self.code.clear()
            self._lock_fields(True)
            self.steps.setCurrentWidget(self.code_box)
            self.title.setText("Подтвердите почту")
            self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.edit.show()
            self.submit.setText("Подтвердить код")
            self.cancel.setText("Назад")
            self.hint.setText("Письмо отправлено на " + self.email.text().strip() + ". Введите шесть цифр из письма.")
            self.code.setFocus()
        else:
            self.registered_email = self.email.text().strip().lower()
            self.password.clear()
            self.confirm.clear()
            self.code.clear()
            self.completed = True
            self.edit.hide()
            self.challenge = ''
            if result and re.fullmatch(r'[A-Za-z0-9_]{3,16}', result) and result.lower() == self.nick.text().strip().lower():
                self.profile_completed = True
                self.nick.setText(result)
                self.steps.hide()
                self.cancel.hide()
                self.title.setText('Готово, ' + result + '!')
                self.hint.setText('Аккаунт создан. Теперь войдите с ником или почтой и паролем.')
                self.submit.setText('Продолжить')
                self.profile_saved.emit(result)
                return
            self.steps.setCurrentWidget(self.nickname_page)
            self.nick.show()
            self.nick.setReadOnly(False)
            self.title.setText('Как тебя зовут в Minecraft?')
            self.title.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.hint.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.hint.setText('Шаг 3 из 3 · Почта подтверждена, аккаунт создан. Осталось выбрать игровой ник — он станет твоим логином NEXUS.')
            self.submit.setText('Завершить регистрацию')
            self.cancel.setText('Настроить позже')
            self.nick.setFocus()

    def accept(self):
        if self.busy:
            return
        clear = getattr(self.client, 'clear_registration_session', None)
        if callable(clear):
            clear()
        super().accept()

    def reject(self):
        if self.busy:
            self.error.setText("Дождитесь ответа сайта. Запрос уже отправлен.")
            return
        self.password.clear()
        self.confirm.clear()
        self.code.clear()
        clear = getattr(self.client, 'clear_registration_session', None)
        if callable(clear):
            clear()
        super().reject()
