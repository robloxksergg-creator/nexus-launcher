from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import urllib.request
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from nexus_launcher.secure_http import open_https, origin

from .config import atomic_write
from .models import WorldPresentation, WorldTheme, WorldView

MAX_FEED_BYTES = 1_048_576
MAX_IMAGE_BYTES = 16 * 1_048_576
MAX_TEXT = 600
VALID_STATUS = {"online", "offline", "maintenance", "development", "closed", "unavailable"}
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


class RemoteWorldContent:
    """Validated, bounded and cached presentation data for official worlds."""

    def __init__(self, feed_url: str, cache_path: Path, official_ids: set[str], timeout: float = 4.0):
        self.feed_url = feed_url.strip()
        self.cache_path = cache_path
        self.official_ids = set(official_ids)
        self.timeout = max(1.0, min(float(timeout), 10.0))

    @staticmethod
    def _text(value, field: str, *, required: bool = False) -> str:
        if value is None and not required:
            return ""
        if not isinstance(value, str) or (required and not value.strip()) or len(value) > MAX_TEXT:
            raise ValueError(f"Invalid remote world field: {field}")
        return value.strip()

    def _asset_url(self, value, field: str, feed_origin) -> str:
        url = self._text(value, field, required=True)
        if origin(url) != feed_origin:
            raise ValueError(f"Remote asset must use the feed origin: {field}")
        return url

    def validate(self, payload) -> dict[str, dict]:
        if isinstance(payload, dict):
            payload = payload.get("worlds")
        if not isinstance(payload, list) or len(payload) > len(self.official_ids):
            raise ValueError("Invalid remote worlds payload")
        feed_origin = origin(self.feed_url)
        result: dict[str, dict] = {}
        for raw in payload:
            if not isinstance(raw, dict):
                raise ValueError("Invalid remote world entry")
            world_id = self._text(raw.get("id"), "id", required=True)
            if world_id not in self.official_ids or world_id in result:
                raise ValueError("Unknown or duplicate remote world")
            item: dict = {"id": world_id}
            for key in ("name", "season", "description", "category"):
                if key in raw:
                    item[key] = self._text(raw[key], key, required=True)
            presentation = raw.get("presentation")
            if presentation is not None:
                if not isinstance(presentation, dict):
                    raise ValueError("Invalid remote presentation")
                kind = self._text(presentation.get("type"), "presentation.type", required=True).lower()
                if kind == "image":
                    image = self._asset_url(presentation.get("image"), "presentation.image", feed_origin)
                    item["presentation"] = {"type": kind, "image": image}
                elif kind == "video":
                    video = self._asset_url(presentation.get("video"), "presentation.video", feed_origin)
                    poster = self._asset_url(presentation.get("poster"), "presentation.poster", feed_origin)
                    fallback = presentation.get("fallbackImage")
                    item["presentation"] = {
                        "type": kind,
                        "video": video,
                        "poster": poster,
                        "fallbackImage": self._asset_url(fallback, "presentation.fallbackImage", feed_origin) if fallback else "",
                    }
                    WorldPresentation(type=kind, video=video, poster=poster).validate()
                else:
                    raise ValueError("Invalid remote presentation type")
            theme = raw.get("theme")
            if theme is not None:
                if not isinstance(theme, dict):
                    raise ValueError("Invalid remote theme")
                accent = self._text(theme.get("accent", "#4aa8ff"), "theme.accent", required=True)
                if not _HEX_COLOR.fullmatch(accent):
                    accent = "#4aa8ff"
                text_mode = self._text(theme.get("textMode", "light"), "theme.textMode", required=True).lower()
                foreground = self._text(theme.get("accentForeground", "#06111d"), "theme.accentForeground", required=True)
                if not _HEX_COLOR.fullmatch(foreground):
                    foreground = "#06111d"
                strength = float(theme.get("overlayStrength", 0.78))
                WorldTheme(accent, foreground, text_mode, strength).validate()
                item["theme"] = {"accent": accent, "accentForeground": foreground, "textMode": text_mode, "overlayStrength": strength}
            status = str(raw.get("status", "unavailable")).lower()
            if status not in VALID_STATUS:
                raise ValueError("Invalid remote world status")
            current = int(raw.get("players", 0))
            maximum = int(raw.get("maxPlayers", 0))
            if current < 0 or maximum < 0 or current > max(maximum, 0) or maximum > 100_000:
                raise ValueError("Invalid remote player count")
            item.update(status=status, players=current, maxPlayers=maximum)
            result[world_id] = item
        return result

    def load_cache(self) -> dict[str, dict]:
        if not self.feed_url or not self.cache_path.is_file():
            return {}
        try:
            return self.validate(json.loads(self.cache_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return {}

    def fetch(self) -> dict[str, dict]:
        if not self.feed_url:
            return {}
        request = urllib.request.Request(
            self.feed_url,
            headers={"Accept": "application/json", "User-Agent": "NEXUS-Launcher/Private-Global-Update"},
        )
        with open_https(request, self.timeout) as response:
            raw = response.read(MAX_FEED_BYTES + 1)
        if len(raw) > MAX_FEED_BYTES:
            raise ValueError("Remote worlds payload is too large")
        payload = json.loads(raw.decode("utf-8"))
        validated = self.validate(payload)
        for world_id, item in validated.items():
            presentation = item.get("presentation", {})
            for field in ("image", "poster", "fallbackImage"):
                if presentation.get(field):
                    self._download_image(presentation[field], world_id, field)
        atomic_write(self.cache_path, {"worlds": list(validated.values())})
        return validated

    def _asset_path(self, url: str, world_id: str, field: str) -> Path:
        suffix = Path(urlsplit(url).path).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("Remote poster must use PNG, JPEG or WebP")
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
        return self.cache_path.parent / "world-assets" / f"{world_id}-{field}-{digest}{suffix}"

    def _download_image(self, url: str, world_id: str, field: str) -> Path:
        target = self._asset_path(url, world_id, field)
        if target.is_file() and 0 < target.stat().st_size <= MAX_IMAGE_BYTES:
            return target
        request = urllib.request.Request(
            url,
            headers={"Accept": "image/webp,image/png,image/jpeg", "User-Agent": "NEXUS-Launcher/Private-Global-Update"},
        )
        with open_https(request, self.timeout) as response:
            content_type = str(getattr(response, "headers", {}).get("Content-Type", "")).split(";", 1)[0].lower()
            if content_type and content_type not in {"image/webp", "image/png", "image/jpeg"}:
                raise ValueError("Remote poster has an unsupported content type")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("Remote poster is empty or too large")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=target.name, suffix=".part", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return target

    def _local_image(self, url: str, world_id: str, field: str) -> str:
        try:
            path = self._asset_path(url, world_id, field)
            return str(path) if path.is_file() else ""
        except (OSError, ValueError):
            return ""

    def apply(self, worlds: list[WorldView], content: dict[str, dict]) -> list[WorldView]:
        result = []
        for world in worlds:
            item = content.get(world.id)
            if not item:
                result.append(world)
                continue
            presentation = world.presentation
            raw_presentation = item.get("presentation")
            if raw_presentation:
                if raw_presentation["type"] == "image":
                    cached_image = self._local_image(raw_presentation["image"], world.id, "image")
                    if cached_image:
                        presentation = WorldPresentation(type="image", image=cached_image).validate()
                else:
                    cached_poster = self._local_image(raw_presentation["poster"], world.id, "poster")
                    cached_fallback = ""
                    if raw_presentation.get("fallbackImage"):
                        cached_fallback = self._local_image(raw_presentation["fallbackImage"], world.id, "fallbackImage")
                    if cached_poster:
                        presentation = WorldPresentation(
                            type="video",
                            video=raw_presentation["video"],
                            poster=cached_poster,
                            fallback_image=cached_fallback or world.presentation.image or world.presentation.poster,
                        ).validate()
            theme = world.theme
            raw_theme = item.get("theme")
            if raw_theme:
                theme = WorldTheme(
                    accent=raw_theme["accent"],
                    accent_foreground=raw_theme.get("accentForeground", "#06111d"),
                    text_mode=raw_theme["textMode"],
                    overlay_strength=raw_theme["overlayStrength"],
                ).validate()
            result.append(replace(
                world,
                title=item.get("name", world.title),
                season=item.get("season", world.season),
                description=item.get("description", world.description),
                category=item.get("category", world.category).upper(),
                presentation=presentation,
                theme=theme,
            ))
        return result
