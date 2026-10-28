import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from nexus_launcher.file_transaction import apply, recover


@pytest.mark.parametrize(
    "phase",
    ["preparing", "copying", "copy_complete", "backup", "prepared", "replace", "state", "committed", "cleanup", "cleanup_partial"],
)
@pytest.mark.parametrize("state_name", ["pack.json", "nexus-pack-manifest.json"])
def test_process_crash_restores_one_complete_generation(tmp_path, phase, state_name):
    root, stage = tmp_path / "game", tmp_path / "stage"
    (root / "mods").mkdir(parents=True)
    (stage / "mods").mkdir(parents=True)
    (root / ".nexus-launcher").mkdir()
    state_path = ".nexus-launcher/" + state_name
    (root / state_path).write_text('{"version":"old"}')
    records = []
    for name in ("a.jar", "b.jar"):
        (root / "mods" / name).write_bytes(b"old")
        (stage / "mods" / name).write_bytes(b"new")
        records.append({"path": "mods/" + name, "sha256": hashlib.sha256(b"new").hexdigest()})
    injection = ""
    if phase == "copying":
        # Model an incomplete temporary file, without depending on which copy
        # backend is selected. This does not claim a native mid-write crash.
        # Journal streams use text mode, so their writes remain untouched.
        injection = """
saved_fdopen = os.fdopen
def interrupt_temporary(fd, mode='r', *args, **kwargs):
    stream = saved_fdopen(fd, mode, *args, **kwargs)
    if mode == 'wb':
        stream.write(b'partial')
        stream.flush()
        os._exit(73)
    return stream
os.fdopen = interrupt_temporary
"""
    if phase == "copy_complete":
        # Execute the real selected copy primitive, then crash before fsync and
        # replacement. The native wrapper must call through, not fake success.
        injection = """
import nexus_launcher.resource_limits as resource_limits
import nexus_launcher.safe_paths as safe_paths
saved_copy = resource_limits.copy_limited
def copied_before_fsync(source, destination, **kwargs):
    saved_copy(source, destination, **kwargs)
    destination.flush()
    os._exit(73)
resource_limits.copy_limited = copied_before_fsync
if os.name == 'nt' and getattr(safe_paths._native, 'COPY_STREAM_API_VERSION', None) == 1:
    saved_native_copy = safe_paths._native.windows_copy_streams
    def native_copied_before_fsync(source, destination, limit):
        saved_native_copy(source, destination, limit)
        os._exit(73)
    safe_paths._native.windows_copy_streams = native_copied_before_fsync
"""
    if phase == "cleanup_partial":
        injection = (
            "import nexus_launcher.safe_paths as safe_paths;saved_unlink=safe_paths.unlink_file;"
            "safe_paths.unlink_file=lambda p,**kw: (saved_unlink(p,**kw),os._exit(73));"
        )
    script = "\n".join((
        "import sys,os",
        f"sys.path.insert(0,{str(Path(__file__).resolve().parents[1])!r})",
        "import nexus_launcher.file_transaction as t",
        injection,
        f"t.checkpoint=lambda p: os._exit(73) if p=={phase!r} else None",
        f"t.apply({str(root)!r},{str(stage)!r},{records!r},[],{state_path!r},{{'version':'new'}})",
    ))
    assert subprocess.run([sys.executable, "-c", script], timeout=20).returncode == 73
    if phase in {"copying", "copy_complete"}:
        temporary = list((root / ".nexus-launcher/file-transaction").rglob("copy-*.tmp"))
        assert len(temporary) == 1
        assert temporary[0].read_bytes() == (b"partial" if phase == "copying" else b"old")
        assert json.loads((root / ".nexus-launcher/file-transaction/journal.json").read_text())["phase"] == "preparing"
    recover(root)
    expected = b"new" if phase in {"committed", "cleanup", "cleanup_partial"} else b"old"
    assert [(root / "mods" / name).read_bytes() for name in ("a.jar", "b.jar")] == [expected, expected]
    assert json.loads((root / state_path).read_text())["version"] == expected.decode()
    recover(root)
    apply(root, stage, records, [], state_path, {"version": "new"})
    assert (root / "mods/a.jar").read_bytes() == b"new"


def test_transaction_traversal_rejected_without_mutation(tmp_path):
    with pytest.raises(ValueError):
        apply(tmp_path, tmp_path, [{"path": "../escape", "sha256": "x"}], [], ".nexus-launcher/pack.json", {})
    assert list(tmp_path.iterdir()) == []
