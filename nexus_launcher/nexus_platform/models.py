from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

from nexus_launcher.projects import ServerProfile, canonical_server_id


@dataclass(frozen=True)
class WorldPresentation:
    type: str = "image"
    image: str = ""
    video: str = ""
    poster: str = ""
    fallback_image: str = ""

    def validate(self) -> "WorldPresentation":
        kind = self.type.lower()
        if kind not in {"image", "video"}:
            raise ValueError("Неизвестный тип презентации мира")
        if kind == "image" and not self.image:
            raise ValueError("Для image-презентации требуется изображение")
        if kind == "video":
            if not self.video or not self.poster:
                raise ValueError("Для video-презентации требуются video и poster")
            suffix = Path(urlparse(self.video).path).suffix.lower()
            if suffix not in {".webm", ".mp4"}:
                raise ValueError("Видео мира должно иметь формат WebM или MP4")
        return self


@dataclass(frozen=True)
class WorldTheme:
    accent: str = "#4aa8ff"
    accent_foreground: str = "#06111d"
    text_mode: str = "light"
    overlay_strength: float = 0.78

    def validate(self) -> "WorldTheme":
        import re
        accent = self.accent if re.fullmatch(r"#[0-9a-fA-F]{6}", self.accent) else "#4aa8ff"
        foreground = self.accent_foreground if re.fullmatch(r"#[0-9a-fA-F]{6}", self.accent_foreground) else "#06111d"
        if self.text_mode not in {"light", "dark"}:
            raise ValueError("Некорректный режим текста")
        if not 0.45 <= self.overlay_strength <= 0.92:
            raise ValueError("Некорректная сила затемнения")
        return replace(self, accent=accent, accent_foreground=foreground)


@dataclass(frozen=True)
class WorldView:
    server: ServerProfile
    title: str
    short_name: str
    season: str
    description: str
    category: str
    presentation: WorldPresentation
    theme: WorldTheme

    @property
    def id(self) -> str:
        return self.server.id


_IDENTITY = {
    "main": ("GEARMORPH", "GM", "SEASON II", "Индустриальный мир технологий, аэронатики и государств.", "TECH", "#48a9ff"),
    "building": ("ARCHVALE", "AV", "FOUNDERS", "Мир архитектуры, поселений и совместного строительства.", "ADVENTURE", "#d9ad67"),
    "pinewood": ("PINEWOOD", "PW", "VANILLA+", "Тихий мир исследования, строительства и уютных приключений.", "VANILLA", "#71c58b"),
    "elderfall": ("ELDERFALL", "EF", "CHAPTER I", "Сюжетный RPG-мир древних земель и забытых легенд.", "RPG", "#bd8cff"),
    "tech": ("IRONVEIL", "IV", "INDUSTRIAL", "Тяжёлая инженерная сборка для больших производств.", "TECH", "#73a6c9"),
}


def world_from_server(server: ServerProfile, asset_path) -> WorldView:
    server = replace(server, id=canonical_server_id(server.id))
    title, short, season, description, category, accent = _IDENTITY.get(
        server.id,
        (server.name.split("•", 1)[0].strip().upper(), server.name[:2].upper(), "NEXUS WORLD", "Мир в библиотеке NEXUS.", "OTHER", "#4aa8ff"),
    )
    artwork = str(asset_path(server.artwork or "nexus-hero.png"))
    return WorldView(
        server,
        title,
        short,
        season,
        description,
        category,
        WorldPresentation(type="image", image=artwork).validate(),
        WorldTheme(accent=accent, accent_foreground="#06111d").validate(),
    )
