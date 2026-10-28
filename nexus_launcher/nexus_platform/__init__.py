"""Private NEXUS platform UI layered over the production launcher core."""

__all__ = ["PlatformLauncher"]


def __getattr__(name):
    # Startup updater needs shared tokens/chrome before the launcher exists.
    # Importing those must not initialize the complete application dependency tree.
    if name == "PlatformLauncher":
        from .window import PlatformLauncher
        globals()[name] = PlatformLauncher
        return PlatformLauncher
    raise AttributeError(name)
