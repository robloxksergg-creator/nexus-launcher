import os
import time

import pytest
from PySide6.QtWidgets import QLineEdit

from nexus_launcher.nexus_account import AccountError, ProtocolError, TransportError
from nexus_launcher.nexus_platform.registration import RegistrationDialog, WebsiteRegistrationClient
from tests.test_next_shell import candidate  # noqa: F401


def test_website_registration_uses_existing_endpoints_and_same_device(monkeypatch):
    client = WebsiteRegistrationClient()
    calls = []
    monkeypatch.setattr(client, "_device_id", lambda: "device-one")

    def request(path, **kwargs):
        calls.append((path, kwargs))
        return ({"ok": True, "challengeId": "challenge-one"}, None)

    monkeypatch.setattr(client, "_request", request)
    challenge = client.request_code(" User@example.com ", "test-password")
    client.register("user@example.com", "Player_1", "test-password", challenge, "123456")
    assert [call[0] for call in calls] == ["/api/auth/email/request-code", "/api/auth/register"]
    assert calls[0][1]["payload"]["deviceId"] == calls[1][1]["payload"]["deviceId"]
    assert calls[0][1]["payload"]["password"] == "test-password"
    assert calls[1][1]["payload"]["challengeId"] == challenge
    assert calls[1][1]["payload"]["email"] == "user@example.com"
    assert calls[1][1]["payload"]["minecraftNick"] == "Player_1"
    assert "token" not in calls[1][1]


@pytest.mark.parametrize('nick', ['', 'ab', 'not a name', 'ЯPlayer', 'x' * 17])
def test_invalid_nickname_never_sends_confirmation(monkeypatch, nick):
    client = WebsiteRegistrationClient()
    def unexpected(*args, **kwargs):
        pytest.fail('invalid nickname reached transport')
    monkeypatch.setattr(client, '_request', unexpected)
    with pytest.raises(AccountError):
        client.register('user@example.com', nick, 'test-password', 'challenge', '123456')


@pytest.mark.parametrize('user,expected', [
    ({'minecraftNick': 'Player_1'}, 'Player_1'),
    ({'minecraftNick': 'PLAYER_1', 'profileCompleted': True}, 'PLAYER_1'),
    ({'minecraftNick': 'Other'}, None),
    ({'minecraftNick': 'Player_1', 'profileCompleted': False}, None),
    ({}, None),
])
def test_profile_completion_requires_server_nickname(monkeypatch, user, expected):
    client = WebsiteRegistrationClient()
    monkeypatch.setattr(client, '_device_id', lambda: 'synthetic-device')
    monkeypatch.setattr(client, '_request', lambda *a, **k: ({'ok': True, 'user': user}, None))
    assert client.register('user@example.com', 'Player_1', 'test-password', 'challenge', '123456') == expected


def test_deployed_registration_completion_skips_profile_mutation(candidate):
    app, window, _ = candidate
    class Client:
        pass
    dialog = RegistrationDialog(Client(), window)
    dialog.show()
    dialog.email.setText('user@example.com')
    dialog.registration_nick.setText('Player_1')
    app.processEvents()
    assert dialog.registration_nick.isVisible()
    assert dialog.nick.text() == 'Player_1'
    dialog._completed('register', 'Player_1', '')
    assert dialog.completed and dialog.profile_completed
    assert dialog.steps.isHidden()
    assert dialog.submit.text() == 'Продолжить'
    assert not dialog.password.text()
    dialog.accept()


def test_missing_nick_blocks_code_request(candidate):
    app, window, _ = candidate
    class Client:
        def request_code(self, *args):
            pytest.fail('missing nickname reached transport')
    dialog = RegistrationDialog(Client(), window)
    dialog.email.setText('user@example.com')
    dialog.password.setText('test-password')
    dialog.confirm.setText('test-password')
    dialog._submit()
    assert not dialog.busy and not dialog.challenge
    assert 'Ник:' in dialog.error.text()
    dialog.reject()


def test_rejects_invalid_code_and_malformed_server_reply(monkeypatch):
    client = WebsiteRegistrationClient()
    monkeypatch.setattr(client, "_request", lambda *a, **k: ({"ok": True}, None))
    monkeypatch.setattr(client, "_device_id", lambda: "test-device")
    with pytest.raises(ProtocolError):
        client.request_code("user@example.com", "test-password")
    with pytest.raises(AccountError):
        client.register("user@example.com", "Player", "test-password", "challenge", "１２３４５６")


def wait_for_dialog(app, dialog):
    deadline = time.monotonic() + 3
    while dialog.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    app.processEvents()
    assert not dialog.busy


def test_registration_two_steps_and_password_cleanup(candidate):  # noqa: F811
    app, window, _ = candidate
    calls = []

    class Client:
        def request_code(self, email, password):
            calls.append(("code", email))
            return "challenge"

        def register(self, *args):
            calls.append(("register", args))

    dialog = RegistrationDialog(Client(), window)
    dialog.show()
    app.processEvents()
    if os.environ.get("NEXUS_REGISTRATION_CAPTURE"):
        assert dialog.grab().save(os.environ["NEXUS_REGISTRATION_CAPTURE"])
    dialog.email.setText("user@example.com")
    dialog.nick.setText("Player")
    dialog.password.setText("test-password")
    dialog.confirm.setText("test-password")
    assert dialog.password.echoMode() == QLineEdit.Password
    dialog._submit()
    dialog._submit()
    wait_for_dialog(app, dialog)
    assert len(calls) == 1
    assert dialog.challenge == "challenge"
    assert dialog.email.isReadOnly()
    assert dialog.code_box.isVisible()
    app.processEvents()
    assert dialog.height() < 720
    assert dialog.submit.geometry().bottom() < dialog.height()
    assert dialog.submit.geometry().right() < dialog.width()
    dialog.code.setText("123456")
    dialog._submit()
    wait_for_dialog(app, dialog)
    assert dialog.registered_email == "user@example.com"
    assert dialog.password.text() == dialog.confirm.text() == dialog.code.text() == ""
    assert len(calls) == 2


def test_transport_error_does_not_claim_success_or_auto_retry(candidate):  # noqa: F811
    app, window, _ = candidate

    class Client:
        def register(self, *args):
            raise TransportError("test")

    dialog = RegistrationDialog(Client(), window)
    dialog.email.setText("user@example.com")
    dialog.nick.setText("Player")
    dialog.password.setText("test-password")
    dialog.confirm.setText("test-password")
    dialog.challenge = "challenge"
    dialog.code.setText("123456")
    dialog._submit()
    wait_for_dialog(app, dialog)
    assert not dialog.registered_email
    assert "мог быть создан" in dialog.error.text()
    dialog.reject()
    assert not dialog.password.text()
