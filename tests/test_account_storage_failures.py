"""Account storage failures must not authenticate or strand the native UI."""
import pytest
from keyring.errors import KeyringError

from nexus_launcher.nexus_account import AccountError, NexusAccountClient
from nexus_launcher.modern_main import Launcher
from tests.test_next_shell import candidate

RESTORE_WORKER = Launcher._restore_account_worker


def test_failed_session_save_is_controlled_and_clears_binding(monkeypatch):
    client = NexusAccountClient("https://example.invalid")
    monkeypatch.setattr(client, "_device_id", lambda: "synthetic-device")
    monkeypatch.setattr(client, "_request", lambda *_, **__: ({
        "token": "a" * 64, "user": {"id": "synthetic-id", "minecraftNick": "Synthetic_User", "email": "synthetic@example.invalid"}}, None))
    def refused(*_): raise KeyringError("private backend diagnostic")
    monkeypatch.setattr("nexus_launcher.nexus_account.keyring.set_password", refused)
    with pytest.raises(AccountError) as caught:
        client.login("Synthetic_User", "synthetic-password")
    assert "сохранить" in str(caught.value)
    assert "private" not in str(caught.value) and "synthetic-password" not in str(caught.value)
    assert client._support_identity is None


def test_failed_session_read_is_controlled(monkeypatch):
    def refused(*_): raise KeyringError("private token diagnostic")
    monkeypatch.setattr("nexus_launcher.nexus_account.keyring.get_password", refused)
    with pytest.raises(AccountError) as caught:
        NexusAccountClient("https://example.invalid").restore()
    assert "прочитать" in str(caught.value) and "private" not in str(caught.value)


@pytest.mark.parametrize("operation", ["login", "restore"])
def test_storage_failure_reenables_portable_account_ui(candidate, monkeypatch, operation):
    app, window, _ = candidate
    messages = []
    monkeypatch.setattr("nexus_launcher.modern_main.QMessageBox.warning", lambda *args: messages.append(args[-1]))
    def refused(*_): raise AccountError("Системное хранилище недоступно. Повторите вход.")
    monkeypatch.setattr(window.account_client, operation, refused)
    window.profile.setEnabled(False)
    if operation == "login":
        window._login_account_worker("Synthetic_User", "synthetic-password")
    else:
        # Call the real worker; fixture replaces it only during construction.
        RESTORE_WORKER(window)
    app.processEvents()
    assert window.profile.isEnabled()
    assert window.account_profile is None
    assert messages == ["Системное хранилище недоступно. Повторите вход."]
