from __future__ import annotations

import gzip
import io
import os
import struct
from pathlib import Path
from typing import Any


def _read_exact(stream: io.BytesIO, size: int) -> bytes:
    value = stream.read(size)
    if len(value) != size:
        raise ValueError("Повреждённый servers.dat")
    return value


def _read_string(stream: io.BytesIO) -> str:
    size = struct.unpack(">H", _read_exact(stream, 2))[0]
    return _read_exact(stream, size).decode("utf-8")


def _read_payload(stream: io.BytesIO, tag: int) -> Any:
    if tag == 1:
        return struct.unpack(">b", _read_exact(stream, 1))[0]
    if tag == 2:
        return struct.unpack(">h", _read_exact(stream, 2))[0]
    if tag == 3:
        return struct.unpack(">i", _read_exact(stream, 4))[0]
    if tag == 4:
        return struct.unpack(">q", _read_exact(stream, 8))[0]
    if tag == 5:
        return struct.unpack(">f", _read_exact(stream, 4))[0]
    if tag == 6:
        return struct.unpack(">d", _read_exact(stream, 8))[0]
    if tag == 7:
        size = struct.unpack(">i", _read_exact(stream, 4))[0]
        return _read_exact(stream, size)
    if tag == 8:
        return _read_string(stream)
    if tag == 9:
        item_tag = _read_exact(stream, 1)[0]
        size = struct.unpack(">i", _read_exact(stream, 4))[0]
        return item_tag, [_read_payload(stream, item_tag) for _ in range(size)]
    if tag == 10:
        result: dict[str, tuple[int, Any]] = {}
        while True:
            child_tag = _read_exact(stream, 1)[0]
            if child_tag == 0:
                return result
            # Read the name before the payload. In a subscript assignment
            # Python evaluates the right-hand side first, which previously
            # advanced the stream in the wrong order and silently discarded
            # every existing server entry on the next launch.
            child_name = _read_string(stream)
            child_value = _read_payload(stream, child_tag)
            result[child_name] = (child_tag, child_value)
    if tag == 11:
        size = struct.unpack(">i", _read_exact(stream, 4))[0]
        return [struct.unpack(">i", _read_exact(stream, 4))[0] for _ in range(size)]
    if tag == 12:
        size = struct.unpack(">i", _read_exact(stream, 4))[0]
        return [struct.unpack(">q", _read_exact(stream, 8))[0] for _ in range(size)]
    raise ValueError(f"Неизвестный NBT-тег: {tag}")


def _write_string(stream: io.BytesIO, value: str) -> None:
    encoded = value.encode("utf-8")
    stream.write(struct.pack(">H", len(encoded)))
    stream.write(encoded)


def _write_payload(stream: io.BytesIO, tag: int, value: Any) -> None:
    if tag == 1:
        stream.write(struct.pack(">b", value))
    elif tag == 2:
        stream.write(struct.pack(">h", value))
    elif tag == 3:
        stream.write(struct.pack(">i", value))
    elif tag == 4:
        stream.write(struct.pack(">q", value))
    elif tag == 5:
        stream.write(struct.pack(">f", value))
    elif tag == 6:
        stream.write(struct.pack(">d", value))
    elif tag == 7:
        stream.write(struct.pack(">i", len(value)))
        stream.write(value)
    elif tag == 8:
        _write_string(stream, value)
    elif tag == 9:
        item_tag, items = value
        stream.write(bytes((item_tag,)))
        stream.write(struct.pack(">i", len(items)))
        for item in items:
            _write_payload(stream, item_tag, item)
    elif tag == 10:
        for name, (child_tag, child_value) in value.items():
            stream.write(bytes((child_tag,)))
            _write_string(stream, name)
            _write_payload(stream, child_tag, child_value)
        stream.write(b"\x00")
    elif tag == 11:
        stream.write(struct.pack(">i", len(value)))
        for item in value:
            stream.write(struct.pack(">i", item))
    elif tag == 12:
        stream.write(struct.pack(">i", len(value)))
        for item in value:
            stream.write(struct.pack(">q", item))
    else:
        raise ValueError(f"Неизвестный NBT-тег: {tag}")


def ensure_server(path: Path, name: str, address: str) -> None:
    """Add or update a Multiplayer entry while preserving other servers."""
    root: dict[str, tuple[int, Any]] = {}
    if path.is_file():
        try:
            encoded = path.read_bytes()
            # Minecraft 1.21.1 writes servers.dat as an uncompressed NBT file.
            # Older launcher builds incorrectly used GZip, so accept both on
            # input and always migrate to the format used by the game.
            raw = gzip.decompress(encoded) if encoded.startswith(b"\x1f\x8b") else encoded
            stream = io.BytesIO(raw)
            if _read_exact(stream, 1)[0] != 10:
                raise ValueError("Корневой NBT-тег не Compound")
            _read_string(stream)
            root = _read_payload(stream, 10)
        except (OSError, EOFError, ValueError, struct.error):
            backup = path.with_suffix(".dat.broken")
            if not backup.exists():
                backup.write_bytes(path.read_bytes())
            root = {}

    list_tag, servers = root.get("servers", (9, (10, [])))
    if list_tag != 9 or servers[0] != 10:
        servers = (10, [])
    entries = servers[1]
    replacement = {
        "name": (8, name),
        "ip": (8, address),
        "hidden": (1, 0),
        "acceptTextures": (1, 1),
    }
    address_key = address.casefold()
    for index, entry in enumerate(entries):
        ip = entry.get("ip", (8, ""))[1] if isinstance(entry, dict) else ""
        entry_name = entry.get("name", (8, ""))[1] if isinstance(entry, dict) else ""
        if str(ip).casefold() == address_key or str(entry_name).casefold() == name.casefold():
            entries[index] = replacement
            break
    else:
        entries.insert(0, replacement)
    root["servers"] = (9, (10, entries))

    stream = io.BytesIO()
    stream.write(b"\x0a\x00\x00")
    _write_payload(stream, 10, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".dat.part")
    temporary.write_bytes(stream.getvalue())
    os.replace(temporary, path)
