"""Actual Qt portable registration handoff, with no account/network operations."""
import os
from pathlib import Path

import pytest

from tests.test_next_shell import candidate


@pytest.mark.parametrize("accepted,complete,expected", [
    (True, True, ["Synthetic_User"]), (True, False, []),
    (False, True, []), (False, False, []),
])
def test_portable_registration_handoff(candidate, monkeypatch, accepted, complete, expected):
    app, window, _ = candidate
    opened = []
    monkeypatch.setattr(window, "_login_account", opened.append)
    window.profile.setEnabled(True)
    window._register_account()
    form = window.page_map["registration"].registration_form
    form.nick.setText("Synthetic_User")
    form.profile_completed = complete
    assert window.account_profile is None
    if accepted:
        form.accept()
    else:
        form.reject()
    # Deferred login must not run while the registration page is being removed.
    assert opened == []
    app.processEvents()
    assert opened == expected
    assert "registration" not in window.page_map
    assert window._current_page == "profile"
    assert window.account_profile is None


def test_portable_registration_does_not_open_duplicate_form(candidate):
    app, window, _ = candidate
    window.profile.setEnabled(True)
    window._register_account()
    page = window.page_map["registration"]
    window._register_account()
    assert window.page_map["registration"] is page
    page.registration_form.reject()
    app.processEvents()


def test_portable_login_prefills_identifier_but_requires_password(candidate, monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    from nexus_launcher.nexus_platform.next_shell import NexusLogin
    app, window, _ = candidate
    observed = []
    def cancel(dialog):
        dialog.show()
        app.processEvents()
        observed.append((dialog.identifier.text(), dialog.password.text(), dialog.password.echoMode()))
        assert dialog.focusWidget() is dialog.password
        capture = os.environ.get("NEXUS_ACCOUNT_CAPTURE_DIR")
        if capture:
            folder = Path(capture); folder.mkdir(parents=True, exist_ok=True)
            assert dialog.grab().save(str(folder / "login.png"))
        dialog.reject()
        return 0
    monkeypatch.setattr(NexusLogin, "exec", cancel)
    monkeypatch.setattr(window, "_login_account_worker", lambda *_: pytest.fail("Cancelled login authenticated"))
    window.profile.setEnabled(True)
    window._login_account("Synthetic_User")
    assert observed == [("Synthetic_User", "", QLineEdit.Password)]
    assert window.account_profile is None


def test_renderer_register_action_opens_native_form_and_returns_to_login(candidate, monkeypatch):
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    from tests.test_design_host import js, wait
    app, services, _ = candidate
    opened = []
    monkeypatch.setattr(services, "_login_account", opened.append)
    services.profile.setEnabled(True)
    host = DesignHost(services)
    services.hide()
    host.resize(1366, 768)
    host.show()
    try:
        wait(app, lambda: bool(js(app, host.page, "typeof window.NexusUI !== 'undefined'")))
        js(app, host.page, "window.NexusUI.navigate('profile')")
        wait(app, lambda: bool(js(app, host.page, "document.querySelector('[data-action=register]') !== null")))
        js(app, host.page, "document.querySelector('[data-action=register]').click()")
        wait(app, lambda: "registration" in services.page_map)
        form = services.page_map["registration"].registration_form
        form.email.setText("synthetic@example.invalid")
        form.password.setText("synthetic-private-password")
        form.nick.setText("Synthetic_User")
        assert services.account_profile is None
        assert not js(app, host.page, "document.body.innerText.includes('synthetic@example.invalid') || document.body.innerText.includes('synthetic-private-password')")
        capture = os.environ.get("NEXUS_ACCOUNT_CAPTURE_DIR")
        if capture:
            folder = Path(capture); folder.mkdir(parents=True, exist_ok=True)
            assert form.grab().save(str(folder / "registration-native.png"))
        # Synthetic confirmed response: exercise the real completion/Continue
        # transition without sending a registration request or granting a session.
        form._completed("profile", "Synthetic_User", "")
        form.accept()
        wait(app, lambda: opened == ["Synthetic_User"])
        assert services.account_profile is None
        assert "registration" not in services.page_map
    finally:
        host.close()
