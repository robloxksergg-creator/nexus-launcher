"""One native authentication owner; renderer never receives credentials."""
import threading
from PySide6.QtCore import QObject, Signal, Qt
from nexus_launcher.nexus_account import AccountError, OfflineError, SessionRejected, TransportError


class AuthState(QObject):
    changed = Signal()
    completed = Signal(str, object, str)

    def __init__(self, client, parent=None):
        super().__init__(parent)
        self.client = client
        self.status = "loading"
        self.connection = "AUTHENTICATING"
        self.user = None
        self.message = "Проверяем сессию NEXUS…"
        self.busy = False
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    def run(self, operation, *args):
        if self.busy:
            return
        self.busy = True
        if self.user is None or operation != "restore":
            self.status = "loading"
        self.connection = "AUTHENTICATING"
        self.message = "Подключаемся к NEXUS…"
        self.changed.emit()

        def work():
            try:
                user = getattr(self.client, operation)(*args)
                self.completed.emit(operation, user, "")
            except SessionRejected:
                self.completed.emit(operation, None, "AUTH_REJECTED" if operation == "login" else "SESSION_EXPIRED")
            except OfflineError:
                self.completed.emit(operation, None, "OFFLINE")
            except TransportError:
                self.completed.emit(operation, None, "SERVER_UNAVAILABLE")
            except AccountError:
                self.completed.emit(operation, None, "AUTH_REJECTED")
            except Exception:
                self.completed.emit(operation, None, "SERVER_UNAVAILABLE")
        threading.Thread(target=work, daemon=True).start()

    def _complete(self, operation, user, error):
        self.busy = False
        self.user = user
        self.status = "authenticated" if user else "unauthenticated"
        self.connection = error or "ONLINE"
        messages = {
            "OFFLINE": "Нет подключения к NEXUS. Проверьте сеть и повторите подключение.",
            "SESSION_EXPIRED": "Сессия NEXUS истекла. Войдите снова.",
            "SERVER_UNAVAILABLE": "Не удалось подключиться к NEXUS. Проверьте подключение и повторите.",
            "AUTH_REJECTED": "Вход отклонён. Проверьте логин и пароль или восстановите доступ к аккаунту.",
        }
        self.message = messages.get(error, "Войдите или создайте аккаунт NEXUS.")
        self.changed.emit()
