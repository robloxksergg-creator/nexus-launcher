from __future__ import annotations

from abc import ABC, abstractmethod


class LoaderProvider(ABC):
    id: str
    title: str

    @abstractmethod
    def default_version(self, minecraft_version: str) -> str:
        raise NotImplementedError

    def normalize(self, minecraft_version: str, loader_version: str) -> str:
        return loader_version.strip() or self.default_version(minecraft_version)


class VanillaProvider(LoaderProvider):
    id, title = "vanilla", "Vanilla"

    def default_version(self, minecraft_version: str) -> str:
        return ""


class FabricProvider(LoaderProvider):
    id, title = "fabric", "Fabric"

    def default_version(self, minecraft_version: str) -> str:
        return "0.16.10"


class NeoForgeProvider(LoaderProvider):
    id, title = "neoforge", "NeoForge"

    def default_version(self, minecraft_version: str) -> str:
        if minecraft_version == "1.21.1":
            return "21.1.235"
        return ""


class ForgeProvider(LoaderProvider):
    id, title = "forge", "Forge"

    def default_version(self, minecraft_version: str) -> str:
        return ""


PROVIDERS = {
    provider.id: provider for provider in (VanillaProvider(), FabricProvider(), NeoForgeProvider(), ForgeProvider())
}


def loader_provider(loader: str) -> LoaderProvider:
    try:
        return PROVIDERS[loader.lower()]
    except KeyError as error:
        raise ValueError(f"Неизвестный загрузчик: {loader}") from error
