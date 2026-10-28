from nexus_launcher.main import App


def test_launcher_window_builds_without_geometry_manager_conflict(monkeypatch):
    monkeypatch.setattr(App, "_load_versions", lambda self: None)
    app = App()
    app.update_idletasks()
    assert app.title() == "NEXUS Launcher"
    app.destroy()
