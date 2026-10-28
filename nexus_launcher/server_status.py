from __future__ import annotations

import json
import socket
import struct


def _varint(value: int) -> bytes:
    result = bytearray()
    while True:
        part = value & 0x7F
        value >>= 7
        result.append(part | (0x80 if value else 0))
        if not value:
            return bytes(result)


def _read_varint(sock: socket.socket) -> int:
    value = 0
    for shift in range(0, 35, 7):
        byte = sock.recv(1)
        if not byte:
            raise ConnectionError("Сервер закрыл соединение")
        value |= (byte[0] & 0x7F) << shift
        if not byte[0] & 0x80:
            return value
    raise ValueError("Некорректный VarInt")


def ping(address: str, timeout: float = 3.0) -> dict:
    host, separator, raw_port = address.strip().partition(":")
    port = int(raw_port) if separator else 25565
    encoded_host = host.encode("utf-8")
    handshake = (
        _varint(0) + _varint(767) + _varint(len(encoded_host)) + encoded_host + struct.pack(">H", port) + _varint(1)
    )
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(_varint(len(handshake)) + handshake + b"\x01\x00")
        _read_varint(sock)
        if _read_varint(sock) != 0:
            raise ValueError("Неожиданный ответ сервера")
        length = _read_varint(sock)
        if length > 1024 * 1024:
            raise ValueError("Ответ сервера слишком большой")
        payload = b""
        while len(payload) < length:
            block = sock.recv(length - len(payload))
            if not block:
                raise ConnectionError("Неполный ответ сервера")
            payload += block
    return json.loads(payload.decode("utf-8"))
