"""Native Apple Silicon desktop entrypoint, without the Windows updater."""
import os
from pathlib import Path
import platform
import sys


def configure_environment():
    if sys.platform != 'darwin' or platform.machine().lower() not in {'arm64', 'aarch64'}:
        raise RuntimeError('This build requires an Apple Silicon Mac')
    if os.geteuid() == 0:
        raise RuntimeError('Run NEXUS as a regular desktop user, not root')
    root = Path.home() / 'Library' / 'Application Support' / 'NEXUS Launcher'
    os.environ['NEXUS_PORTABLE_DATA'] = str(root)
    os.environ['NEXUS_UI_2'] = '1'
    os.environ['NEXUS_DISABLE_SELF_UPDATE'] = '1'
    return root


def main():
    configure_environment()
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from nexus_launcher.preview_prototype import main as run
    return run()


if __name__ == '__main__':
    sys.exit(main())
