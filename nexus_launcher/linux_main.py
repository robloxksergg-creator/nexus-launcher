"""Linux desktop entrypoint; intentionally separate from the Windows updater."""
import os
from pathlib import Path
import sys


def configure_environment():
    if not sys.platform.startswith('linux'):
        raise RuntimeError('This launcher entrypoint requires Linux')
    # Qt WebEngine must retain its sandbox; running a desktop app as root is
    # neither required nor supported. Never add --no-sandbox here.
    if os.geteuid() == 0:
        raise RuntimeError('Run NEXUS as a regular desktop user, not root')
    base = os.environ.get('XDG_DATA_HOME')
    data = Path(base) if base and Path(base).is_absolute() else Path.home() / '.local' / 'share'
    root = data / 'nexus-launcher'
    # Select before any application/storage module is imported. The existing
    # shared UI otherwise uses an ephemeral preview directory.
    os.environ['NEXUS_PORTABLE_DATA'] = str(root)
    os.environ['XDG_DATA_HOME'] = str(data)
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
