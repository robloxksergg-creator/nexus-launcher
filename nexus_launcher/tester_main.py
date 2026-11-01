"""Controlled tester client using the real staging account API."""
import json
import logging
import os
import sys
from pathlib import Path


def _validate_tester_config(config):
    from nexus_launcher.secure_http import origin
    expected = "https://nexusmc-control-plane-staging.robloxksergg.workers.dev"
    if not isinstance(config, dict) or not isinstance(config.get("api"), str):
        raise ValueError("Invalid tester configuration")
    if origin(config["api"]) != origin(expected) or config["api"].rstrip("/") != expected or config.get("channel") != "beta":
        raise ValueError("Tester configuration must use the staging backend")


def _registration_surface(parent, client, finished):
    """Native authentication page; never opens a top-level registration window."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget, QVBoxLayout
    from nexus_launcher.nexus_platform.registration import RegistrationDialog
    page = QWidget(parent)
    page.setObjectName("platformRoot")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(24, 24, 24, 24)
    form = RegistrationDialog(client, page)
    form.setWindowFlags(Qt.WindowType.Widget)
    form.setMaximumWidth(560)
    layout.addStretch()
    layout.addWidget(form, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch()
    page.registration_form = form
    form.finished.connect(lambda result: finished(page, bool(result)))
    return page


def main(*, offline_policy=None, readiness_callback=None):
    if offline_policy is not None:
        from nexus_launcher.offline_ui_policy import OfflineUIPolicy
        if not isinstance(offline_policy, OfflineUIPolicy):
            raise ValueError("Invalid offline UI policy")
        offline_policy.require_installed()
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    config = json.loads((root / "assets/tester-release.json").read_text(encoding="utf-8"))
    _validate_tester_config(config)
    import nexus_launcher.build_channel as build_channel
    build_channel.STAGING_BUILD = True
    build_channel.TESTER_BUILD = True
    os.environ["NEXUS_ENVIRONMENT"] = "staging"
    os.environ["NEXUS_UI_2"] = "1"
    os.environ["NEXUS_TESTER_VERSION"] = config["version"]
    os.environ["NEXUS_DISABLE_SELF_UPDATE"] = "1"
    # Installed client data is independent from previous portable candidates.
    data = (offline_policy.profile if offline_policy is not None else
            Path(os.environ["LOCALAPPDATA"]) / "NEXUS Tester" / config["channel"])
    data.mkdir(parents=True, exist_ok=True)
    from nexus_launcher.launcher_diagnostics import install as install_diagnostics, record as record_diagnostic
    try:
        install_diagnostics(data / 'diagnostics')
    except OSError:
        pass
    logging.basicConfig(filename=data / "tester.log", level=logging.INFO, format="%(asctime)s %(message)s")
    logging.info("startup")
    os.environ["APPDATA"] = str(data)
    os.environ["NEXUS_PORTABLE_DATA"] = str(data)
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
    if offline_policy is not None:
        offline_policy.install_qt_guards()
    from nexus_launcher.nexus_account import NexusAccountClient
    from nexus_launcher.nexus_platform.next_shell import NexusLauncher, NexusLogin
    from nexus_launcher.nexus_platform.design_bridge import DesignHost
    from nexus_launcher.nexus_platform.auth_state import AuthState

    class TesterServices(NexusLauncher):
        auth: AuthState
        def _check_servers(self):
            if offline_policy is None:
                return super()._check_servers()

        def _refresh_remote_content(self):
            if offline_policy is None:
                return super()._refresh_remote_content()

        def _refresh_build_access_worker(self):
            if offline_policy is None:
                return super()._refresh_build_access_worker()

        def _play(self):
            if offline_policy is not None:
                return self.status.setText("Запуск игры отключён в offline UI-тесте.")
            return super()._play()

        def _repair_pack(self):
            if offline_policy is not None:
                return self.status.setText("Загрузка и обновление отключены в offline UI-тесте.")
            return super()._repair_pack()

        def _stop_game(self):
            if offline_policy is not None:
                return self.status.setText("Управление процессами отключено в offline UI-тесте.")
            return super()._stop_game()

        def _restore_account_worker(self):
            pass  # AuthState owns startup restore before revealing the launcher.

        def _login_account_worker(self, identifier, password, totp_code="", recovery_code=""):
            self.auth.run("login", identifier, password, totp_code=totp_code, recovery_code=recovery_code)

        def _logout_account(self):
            self.auth.run("logout")

        def _refresh_account(self):
            self.auth.run("restore")

    app = QApplication(sys.argv)
    app.setApplicationName("NEXUS")
    app.setApplicationVersion(config["version"])
    services = TesterServices()
    services.account_client = NexusAccountClient(config["api"], strict_restore=True)
    if "--smoke-report" in sys.argv:
        services.account_client.keyring_service += " / isolated-smoke"
    auth = AuthState(services.account_client, services)
    services.auth = auth
    host = DesignHost(services)
    host.setWindowTitle(f"NEXUS {config['version']} · " + ("OFFLINE UI TEST" if offline_policy is not None else "тестовая версия"))
    gate = QWidget()
    gate.setObjectName("platformRoot")
    layout = QVBoxLayout(gate)
    layout.setContentsMargins(48, 40, 48, 40)
    layout.addStretch()
    row = QHBoxLayout()
    row.addStretch()
    panel = QWidget()
    panel.setMaximumWidth(640)
    form = QVBoxLayout(panel)
    form.setSpacing(14)
    row.addWidget(panel, 1)
    row.addStretch()
    layout.addLayout(row)
    brand = QLabel("NEXUS")
    brand.setObjectName("pageTitle")
    form.addWidget(brand)
    form.addWidget(QLabel("Открой свой мир."))
    notice = QLabel(f"Тестовая версия {config['version']}. Возможны ошибки и сброс тестовых данных.")
    notice.setWordWrap(True)
    form.addWidget(notice)
    message = QLabel()
    message.setTextFormat(Qt.TextFormat.PlainText)
    message.setWordWrap(True)
    message.setMinimumHeight(48)
    form.addWidget(message)
    login = QPushButton("Войти")
    login.setObjectName("primaryAction")
    register = QPushButton("Создать аккаунт")
    retry = QPushButton("Повторить подключение")
    for button in (login, register, retry):
        form.addWidget(button)
    layout.addStretch()
    host.surfaces.addWidget(gate)
    host.surfaces.setCurrentWidget(gate)
    registration_page = None

    def finish_registration(page, registered):
        nonlocal registration_page
        form = page.registration_form
        identifier = form.nick.text().strip() if registered and form.profile_completed else ''
        host.surfaces.removeWidget(page)
        registration_page = None
        host.surfaces.setCurrentWidget(gate)
        message.setText("Аккаунт создан. Теперь войдите с той же почтой и паролем." if registered else auth.message)
        page.deleteLater()
        if identifier:
            # Context-bound: closing the host cancels the deferred transition.
            QTimer.singleShot(0, host, lambda: sign_in(identifier))

    def sign_up():
        nonlocal registration_page
        if auth.busy:
            return
        if registration_page is None:
            from nexus_launcher.nexus_platform.registration import WebsiteRegistrationClient
            registration_page = _registration_surface(host.surfaces, WebsiteRegistrationClient(services.account_client.base_url), finish_registration)
            host.surfaces.addWidget(registration_page)
        host.surfaces.setCurrentWidget(registration_page)

    def sign_in(identifier=''):
        if auth.busy:
            return
        dialog = NexusLogin(host)
        if isinstance(identifier, str) and identifier:
            dialog.identifier.setText(identifier)
            dialog.password.setFocus()
        if dialog.exec():
            identifier, password = dialog.credentials()
            totp_code, recovery_code = dialog.second_factor()
            dialog.password.clear()
            auth.run("login", identifier, password, totp_code=totp_code, recovery_code=recovery_code)
        else:
            dialog.password.clear()

    login.clicked.connect(sign_in)
    register.clicked.connect(sign_up)
    retry.clicked.connect(lambda: auth.run("restore"))

    def update():
        logging.info("auth state=%s connection=%s", auth.status, auth.connection)
        user = auth.user
        if auth.status == "authenticated" and user is not None:
            services._account_ready(user)
            host.surfaces.setCurrentWidget(host.view)
            message.setText(f"Добро пожаловать, {user.display_name}.")
        else:
            services.account_profile = None
            services.config.pop("username", None)
            services._save_config()
            host.library_overlay.hide()
            host._library_active = False
            if registration_page is None:
                host.surfaces.setCurrentWidget(gate)
            message.setText(auth.message)
        services.profile.setEnabled(not auth.busy)
        for button in (login, register, retry):
            button.setEnabled(not auth.busy)
        retry.setVisible(auth.connection in {"OFFLINE", "SERVER_UNAVAILABLE"})
        host._sync_state(True)

    session_timer = QTimer(host)
    session_timer.setInterval(300000)
    session_timer.timeout.connect(lambda: auth.run("restore") if auth.user and not auth.busy else None)
    session_timer.start()
    auth.changed.connect(update)
    update()
    host.showMaximized()
    QTimer.singleShot(0, lambda: auth.run("restore"))
    if readiness_callback is not None:
        from nexus_launcher.startup_readiness import TesterReadinessProbe
        host.bootstrap_readiness = TesterReadinessProbe(host, services, auth, gate, (login, register), readiness_callback)
    if "--smoke-report" in sys.argv:
        output = Path(sys.argv[sys.argv.index("--smoke-report") + 1])
        def report():
            output.write_text(json.dumps({"version":config["version"],"api":config["api"],"state":auth.status,"gateVisible":host.surfaces.currentWidget() is gate,"maximized":host.isMaximized(),"size":[host.width(),host.height()],"scriptErrors":host.page.script_errors}),encoding="utf-8")
            host.grab().save(str(output.with_suffix(".png")))
            host.close()
            app.quit()
        QTimer.singleShot(20000, report)
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        from nexus_launcher.launcher_diagnostics import record as record_diagnostic
        record_diagnostic('python_main', 'unhandled_exception')
        logging.error("fatal category=%s", type(error).__name__)
        from PySide6.QtWidgets import QApplication, QMessageBox
        application = QApplication.instance() or QApplication([])
        message = QMessageBox()
        message.setWindowTitle("NEXUS")
        message.setText("Не удалось запустить NEXUS. Проверьте установку и повторите запуск. Диагностика сохранена в журнале тестовой версии.")
        message.setIcon(QMessageBox.Icon.Critical)
        message.exec()
        sys.exit(1)
