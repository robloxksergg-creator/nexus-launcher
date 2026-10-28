import io

from nexus_launcher.servers_dat import _read_payload, _read_string, ensure_server


def test_ensure_server_preserves_and_updates_entries(tmp_path):
    target = tmp_path / "servers.dat"
    ensure_server(target, "Other", "other.example:25565")
    ensure_server(target, "GEARMORPH • NEXUS", "5.83.140.209:25698")
    ensure_server(target, "GEARMORPH • NEXUS", "5.83.140.209:25698")

    raw = target.read_bytes()
    assert raw.startswith(b"\x0a\x00\x00")
    # Re-reading the file exercises the complete decoder and must not duplicate.
    ensure_server(target, "GEARMORPH • NEXUS", "5.83.140.209:25698")
    stream = io.BytesIO(target.read_bytes())
    assert stream.read(1) == b"\x0a"
    assert _read_string(stream) == ""
    root = _read_payload(stream, 10)
    entries = root["servers"][1][1]
    assert [entry["name"][1] for entry in entries] == ["GEARMORPH • NEXUS", "Other"]
