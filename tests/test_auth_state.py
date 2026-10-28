import time
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication
from nexus_launcher.nexus_account import NexusAccountClient, NexusProfile, OfflineError, SessionRejected, TransportError
from nexus_launcher.nexus_platform.auth_state import AuthState


def settled(app, state):
    deadline = time.monotonic() + 3
    while state.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert not state.busy


def test_auth_state_restores_logs_out_and_recovers():
    app = QApplication.instance() or QApplication([])
    class Client:
        def restore(self):
            return NexusProfile("Player", "test@example.invalid", tester=True)
        def logout(self):
            return None
        def login(self, *_):
            raise TransportError("private server detail")
    state = AuthState(Client())
    state.run("restore")
    settled(app, state)
    assert state.status == "authenticated" and state.user.tester
    state.run("logout")
    settled(app, state)
    assert state.user is None and state.status == "unauthenticated"
    state.run("login", "Player", "fixture")
    settled(app, state)
    assert state.connection == "SERVER_UNAVAILABLE"
    assert "private" not in state.message
    state.run("restore")
    settled(app, state)
    assert state.status == "authenticated"


def test_strict_session_expiration_and_staging_namespace():
    client = NexusAccountClient("https://nexusmc-control-plane-staging.robloxksergg.workers.dev", strict_restore=True)
    assert client.keyring_service.endswith(" / staging")
    with patch("nexus_launcher.nexus_account.keyring.get_password", return_value="a" * 64), patch("nexus_launcher.nexus_account.keyring.delete_password") as delete, patch.object(client, "_request", side_effect=SessionRejected("expired")):
        with pytest.raises(SessionRejected):
            client.restore()
        delete.assert_called_once()
    with patch("nexus_launcher.nexus_account.keyring.get_password", return_value="a" * 64), patch("nexus_launcher.nexus_account.keyring.delete_password") as delete, patch.object(client, "_request", side_effect=TransportError("offline")):
        with pytest.raises(TransportError):
            client.restore()
        delete.assert_not_called()
        with pytest.raises(TransportError):
            client.logout()
        delete.assert_called_once()


def test_offline_state_has_explicit_recovery():
    app = QApplication.instance() or QApplication([])
    class Client:
        def restore(self):
            raise OfflineError("fixture")
    state = AuthState(Client())
    state.run("restore")
    settled(app, state)
    assert state.connection == "OFFLINE"
    assert state.status == "unauthenticated"
    assert state.user is None
    assert "сеть" in state.message


def test_wrong_password_is_not_presented_as_expired_session():
    app = QApplication.instance() or QApplication([])
    class Client:
        def login(self, *_):
            raise SessionRejected("wrong password")
    state = AuthState(Client())
    state.run("login", "Player", "wrong")
    settled(app, state)
    assert state.connection == "AUTH_REJECTED"
    assert "истекла" not in state.message
