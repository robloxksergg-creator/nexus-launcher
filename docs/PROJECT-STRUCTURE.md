# Project structure

- `nexus_launcher/` contains the launcher, runtime services, build utilities, and entry points.
- `nexus_launcher/nexus_platform/` contains the desktop UI package.
- `tests/` contains Python and JavaScript tests plus test fixtures.
- `assets/` contains application resources; visual captures are in `assets/previews/`.
- `docs/` contains project contracts, audits, and design notes.
- `packaging/specs/` contains PyInstaller specifications; `packaging/metadata/` contains version resources.
- `packaging/requirements/` contains optional dependency sets. The primary dependency list remains `requirements.txt`.

Run from the repository root:

```powershell
python -m nexus_launcher.stable_main
python -m pytest
python -m PyInstaller packaging/specs/NexusLauncher.spec
```

Local project imports use the `nexus_launcher` package, for example
`from nexus_launcher.projects import ProjectCatalog`.
