"""Production-service child for the separately provisioned managed preview."""
import hashlib
import os
from pathlib import Path
import sys


def main():
    import nexus_launcher.build_channel as channel
    channel.PUBLIC_PREVIEW_BUILD = True
    from nexus_launcher.windows_bootstrap_process import BootstrapChildSession
    session = BootstrapChildSession.receive()
    try:
        from nexus_launcher.portable_storage import managed_portable_data_root
        from nexus_launcher.portable_transition import _read
        from nexus_launcher.signed_release import canonical
        executable = Path(sys.executable).absolute()
        root = managed_portable_data_root(executable)
        envelope = _read(executable.parent.parent, 'envelope.json')
        if hashlib.sha256(canonical(envelope['release'])).hexdigest() != session.challenge.candidate_identity:
            raise ValueError('Bootstrap package identity mismatch')
        from nexus_launcher.safe_paths import pinned_directory
        with pinned_directory(root, create=True):
            os.environ['NEXUS_PORTABLE_DATA'] = str(root)
            os.environ['NEXUS_UI_2'] = '1'
            from nexus_launcher.preview_prototype import main as run
            return run(readiness_callback=session.ready)
    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
