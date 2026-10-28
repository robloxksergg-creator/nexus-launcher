"""Offline packaged-binary acceptance. Never requests email, login or credentials."""
import json
from pathlib import Path

import keyring
from nexus_launcher.nexus_account import API_BASE
from nexus_launcher.nexus_platform.registration import RegistrationDialog, WebsiteRegistrationClient


def check(app, window, report_path):
    window.show_instances()
    app.processEvents()
    client = WebsiteRegistrationClient(window.account_client.base_url)
    dialog = RegistrationDialog(client, window)
    dialog.show()
    app.processEvents()
    initial = dialog.submit.isVisible()
    dialog._completed("code", "offline-smoke-challenge", "")
    app.processEvents()
    report = {
        "main_window_visible": window.isVisible(),
        "registration_button_visible": window.registration_button.isVisible(),
        "registration_initial_submit": initial,
        "registration_code_visible": dialog.code_box.isVisible(),
        "account_api": API_BASE,
        "keyring_backend": type(keyring.get_keyring()).__module__,
        "network_calls": 0,
    }
    assert all(report[name] for name in (
        "main_window_visible", "registration_button_visible", "registration_initial_submit", "registration_code_visible"
    ))
    assert "staging" not in API_BASE
    dialog.reject()
    window.close()
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
