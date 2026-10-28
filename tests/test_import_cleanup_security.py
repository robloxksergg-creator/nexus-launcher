import json
from types import SimpleNamespace

import pytest
from nexus_launcher.curseforge_importer import CurseForgeImporter


@pytest.mark.parametrize("fail", [False, True])
def test_staging_cleanup_only_removes_this_invocation(tmp_path, monkeypatch, fail):
    importer = CurseForgeImporter(tmp_path / "instance", "test")
    old = tmp_path / ".staging/test"
    old.mkdir(parents=True)
    sentinel = old / "original"
    sentinel.write_bytes(b"keep")
    monkeypatch.setattr("nexus_launcher.curseforge_importer.inspect_pack", lambda _: (SimpleNamespace(), {}))
    used = []

    def install(*args):
        staging = args[-1]
        used.append(staging)
        (staging / "partial").write_bytes(b"owned")
        if fail:
            raise ValueError("fixture failure")
        return {"done": True}

    monkeypatch.setattr(importer, "_install_staged", install)
    if fail:
        with pytest.raises(ValueError, match="fixture failure"):
            importer.install(tmp_path / "unused.zip")
    else:
        assert importer.install(tmp_path / "unused.zip") == {"done": True}
    assert sentinel.read_bytes() == b"keep"
    assert used and not used[0].exists()
    assert list(old.parent.iterdir()) == [old]


def test_state_write_does_not_overwrite_unowned_part(tmp_path):
    importer = CurseForgeImporter(tmp_path / "instance", "test")
    importer.state_path.parent.mkdir(parents=True)
    sentinel = importer.state_path.with_suffix(".json.part")
    sentinel.write_bytes(b"keep")
    importer._write_state({"files": []})
    assert sentinel.read_bytes() == b"keep"
    assert json.loads(importer.state_path.read_text()) == {"files": []}
    assert not list(importer.state_path.parent.glob("pack-state-*.tmp"))
