"""Expected digests from CurseForge's official API, never from downloaded bytes."""

import json
import re
import urllib.request

from nexus_launcher.resource_limits import MAX_FILE_BYTES, read_limited
from nexus_launcher.safe_paths import relative_parts
from nexus_launcher.secure_http import open_https


def expected_file(project_id: int, file_id: int, api_key: str) -> dict:
    if not api_key:
        raise ValueError(
            "В архиве нет SHA-256, а официальный CurseForge API не настроен. "
            "Нужен проверенный manifest с хешами либо ключ CurseForge API; файл не установлен."
        )
    if project_id <= 0 or file_id <= 0:
        raise ValueError("Некорректный CurseForge ID")
    request = urllib.request.Request(
        f"https://api.curseforge.com/v1/mods/{project_id}/files/{file_id}",
        headers={"Accept": "application/json", "x-api-key": api_key},
    )
    # No CDN redirects for the credentialed metadata request.
    with open_https(request, timeout=20, allowed_hosts={"api.curseforge.com"}) as response:
        payload = json.loads(read_limited(response))
    data = payload.get("data") if isinstance(payload, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("id") != file_id
        or data.get("modId") != project_id
        or data.get("isAvailable") is not True
    ):
        raise ValueError("CurseForge metadata не соответствует запрошенному файлу")
    name, size = data.get("fileName"), data.get("fileLength")
    if len(relative_parts(name)) != 1 or type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
        raise ValueError("Некорректное имя или размер файла CurseForge")
    hashes = data.get("hashes")
    if not isinstance(hashes, list):
        raise ValueError("CurseForge API не вернул ожидаемый hash")
    if any(
        not isinstance(item, dict)
        or (
            item.get("algo") == 1
            and (not isinstance(item.get("value"), str) or not re.fullmatch(r"[a-fA-F0-9]{40}", item["value"]))
        )
        for item in hashes
    ):
        raise ValueError("CurseForge API вернул некорректный hash")
    # API exposes SHA-1 and MD5, not SHA-256. Do not accept MD5 alone.
    values = {
        item.get("value", "").lower()
        for item in hashes
        if isinstance(item, dict)
        and item.get("algo") == 1
        and isinstance(item.get("value"), str)
        and re.fullmatch(r"[a-fA-F0-9]{40}", item["value"])
    }
    if len(values) != 1:
        raise ValueError("CurseForge API не вернул однозначный SHA-1")
    return {"name": name, "size": size, "sha1": values.pop()}
