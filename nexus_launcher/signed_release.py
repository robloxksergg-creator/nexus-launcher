"""Ed25519 release envelope. Keys come only from the packaged trust store."""

import base64
import json
from datetime import UTC, datetime

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from nexus_launcher.release_metadata import METADATA


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
        "utf-8"
    )


def verify_signature(envelope: dict, *, keys=None) -> dict:
    """Authenticate persisted metadata without treating expiry as loss of history."""
    keys = METADATA["trusted_update_keys"] if keys is None else keys
    if not isinstance(envelope, dict) or envelope.get("schema") != 2:
        raise ValueError("Обновление не подписано поддерживаемым ключом")
    payload = envelope.get("release")
    key_id = envelope.get("key_id")
    if not isinstance(key_id, str):
        raise ValueError("Некорректный идентификатор ключа")
    key = keys.get(key_id)
    if not key or not isinstance(payload, dict):
        raise ValueError("Нет доверенного ключа подписи обновления")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(
            base64.b64decode(envelope["signature"], validate=True), canonical(payload)
        )
    except (InvalidSignature, KeyError, ValueError, TypeError) as error:
        raise ValueError("Подпись обновления не прошла проверку") from error
    if payload.get("channel") != METADATA["channel"]:
        raise ValueError("Другой канал обновления")
    return payload


def verify_envelope(envelope: dict, *, keys=None) -> dict:
    payload = verify_signature(envelope, keys=keys)
    try:
        expiry = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        published = datetime.fromisoformat(payload["published_at"].replace("Z", "+00:00"))
        now = datetime.now(UTC)
        if not published <= now < expiry:
            raise ValueError("Манифест ещё не действует или устарел")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Некорректный срок действия манифеста") from error
    return payload
