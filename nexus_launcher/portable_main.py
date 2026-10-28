"""Persistent, separate portable candidate. Never uses installed launcher storage."""
import os
import sys
from pathlib import Path


def portable_data_root():
    executable = Path(sys.executable).resolve()
    # All managed versions share the installation data root, never slot/data.
    # Ambient NEXUS_PORTABLE_DATA still cannot redirect a normal portable build.
    if (executable.parent.name == "files"
            and executable.parent.parent.name.startswith("portable-stage-")
            and executable.parent.parent.parent.name == "slots"):
        from nexus_launcher.portable_storage import managed_portable_data_root
        return managed_portable_data_root(executable)
    return executable.parent / "data"


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--connection-check-report":
        import json
        from nexus_launcher.connection_diagnostics import probe_account_connection
        Path(sys.argv[2]).write_text(json.dumps(probe_account_connection(), indent=2), encoding="utf-8")
        return
    root = portable_data_root()
    from nexus_launcher.safe_paths import pinned_directory
    # Keep Windows ancestors pinned for the whole app lifetime, not just check.
    with pinned_directory(root, create=True):
        os.environ["NEXUS_PORTABLE_DATA"] = str(root)
        os.environ["NEXUS_UI_2"] = "1"
        from nexus_launcher.preview_prototype import main as run
        run()


if __name__ == "__main__":
    main()
