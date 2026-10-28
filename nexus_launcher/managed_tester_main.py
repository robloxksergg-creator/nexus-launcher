"""Managed tester child. Must be launched through the private bootstrap channel."""
import hashlib
from pathlib import Path
import sys


def main():
    import nexus_launcher.build_channel as build_channel
    build_channel.STAGING_BUILD = True
    build_channel.TESTER_BUILD = True
    from nexus_launcher.windows_bootstrap_process import BootstrapChildSession
    session = BootstrapChildSession.receive()
    try:
        from nexus_launcher.portable_storage import managed_portable_data_root
        from nexus_launcher.portable_transition import _read
        from nexus_launcher.signed_release import canonical
        executable = Path(sys.executable).absolute()
        # Authenticates receipt, signature, selected/launching slot and own EXE.
        managed_portable_data_root(executable)
        envelope = _read(executable.parent.parent, 'envelope.json')
        identity = hashlib.sha256(canonical(envelope['release'])).hexdigest()
        if identity != session.challenge.candidate_identity:
            raise ValueError('Bootstrap package identity mismatch')
        from nexus_launcher.tester_main import main as run
        # Preserve the existing tester account/profile location. Package updates
        # must not migrate account tokens or reset settings implicitly.
        return run(readiness_callback=session.ready)
    finally:
        session.close()


if __name__ == '__main__':
    sys.exit(main())
