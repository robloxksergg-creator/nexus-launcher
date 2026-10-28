import hashlib
import io
import json
from unittest.mock import patch

import pytest

from nexus_launcher.updater import InstallState, ModpackUpdater, PackFile, PackRelease


class Response(io.BytesIO):
    def __init__(self, data: bytes, *, status=200, content_range=""):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}
        if content_range:
            self.headers["Content-Range"] = content_range

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def release_for(content=b"new-content", version="2"):
    entry = PackFile("x", "x.jar", version, "mods/x.jar", "https://nexusmc.flux-productions.com/x.jar",
                     len(content), hashlib.sha256(content).hexdigest(), True, "mod")
    return PackRelease(version, "", "", pack="world", files=(entry,)), entry


def test_interrupted_download_keeps_working_version_and_persists_failure(tmp_path):
    target = tmp_path / "mods" / "x.jar"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"working")
    state = tmp_path / ".nexus-launcher"
    state.mkdir()
    (state / "pack.json").write_text(json.dumps({"version": "1", "managed_files": {
        "mods/x.jar": hashlib.sha256(b"working").hexdigest()}, "last_successful_update": 1}))
    release, _entry = release_for()
    with patch("nexus_launcher.updater.open_https", side_effect=ConnectionError("network down")):
        with pytest.raises(ConnectionError):
            ModpackUpdater(tmp_path, instance_id="world")._sync_files(release)
    assert target.read_bytes() == b"working"
    snapshot = ModpackUpdater(tmp_path, instance_id="world").delivery_snapshot()
    assert snapshot.state == InstallState.FAILED
    assert snapshot.error_kind == "network"


def test_restart_resumes_hash_bound_partial_with_http_range(tmp_path):
    content = b"abcdefgh"
    release, entry = release_for(content)
    updater = ModpackUpdater(tmp_path, instance_id="world")
    stage = updater._stage_path(release, entry)
    stage.parent.mkdir(parents=True)
    stage.write_bytes(content[:3])
    response = Response(content[3:], status=206, content_range=f"bytes 3-{len(content)-1}/{len(content)}")
    with patch("nexus_launcher.updater.open_https", return_value=response) as opened:
        updater._sync_files(release)
    assert opened.call_args.args[0].headers["Range"] == "bytes=3-"
    assert (tmp_path / "mods" / "x.jar").read_bytes() == content
    assert updater.delivery_snapshot().state == InstallState.READY


def test_server_ignoring_range_restarts_partial_instead_of_appending(tmp_path):
    content = b"abcdefgh"
    release, entry = release_for(content)
    updater = ModpackUpdater(tmp_path, instance_id="world")
    stage = updater._stage_path(release, entry)
    stage.parent.mkdir(parents=True)
    stage.write_bytes(content[:3])
    with patch("nexus_launcher.updater.open_https", return_value=Response(content, status=200)):
        updater._sync_files(release)
    assert (tmp_path / "mods" / "x.jar").read_bytes() == content


def test_repair_preserves_player_data_and_reports_only_managed_damage(tmp_path):
    release, entry = release_for()
    save = tmp_path / "saves" / "world" / "level.dat"
    save.parent.mkdir(parents=True)
    save.write_bytes(b"player-save")
    updater = ModpackUpdater(tmp_path, instance_id="world")
    with patch("nexus_launcher.updater.fetch_manifest", return_value=release), patch("nexus_launcher.updater.open_https", return_value=Response(b"new-content")):
        result = updater.repair("https://nexusmc.flux-productions.com/manifest.json")
    assert result.repaired == 0  # first install has no corrupt managed inventory
    assert save.read_bytes() == b"player-save"
    assert updater.delivery_snapshot().state == InstallState.READY


def test_progress_phases_do_not_report_network_speed_during_verify(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from nexus_launcher.nexus_platform.pages import DownloadsPage
    from nexus_launcher.updater import DownloadProgress
    app = QApplication.instance() or QApplication([])
    page = DownloadsPage()
    page.update_event(DownloadProgress("op", "world", "downloading", "mods/x.jar", 5, 10, 1.0), "WORLD")
    page.update_event(DownloadProgress("op", "world", "downloading", "mods/x.jar", 8, 10, 2.0), "WORLD")
    page.update_event(DownloadProgress("op", "world", "verifying", "mods/x.jar", 10, 10, 3.0), "WORLD")
    assert "без использования сети" in page.telemetry.text()
    assert page.detail.toolTip() == "mods/x.jar"

