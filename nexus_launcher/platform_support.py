from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

JAVA_REQUIRED_MAJOR = 21


def platform_id() -> str:
    return "windows" if sys.platform == "win32" else "macos" if sys.platform == "darwin" else "linux"


def architecture_id() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else "x64"


def app_data_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.getenv("APPDATA", Path.home())) / ".nexus-launcher"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NEXUS Launcher"
    return Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "nexus-launcher"


def _java_executable(home_or_executable: str | Path) -> Path:
    value = Path(home_or_executable).expanduser()
    if value.name.lower() in {"java", "java.exe", "javaw.exe"}:
        return value
    return value / "bin" / ("java.exe" if sys.platform == "win32" else "java")


def java_major(executable: str | Path) -> int | None:
    """Read the actual JVM version instead of trusting a directory name."""
    try:
        result = subprocess.run(
            [str(executable), "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **hidden_process_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = result.stderr or result.stdout
    match = re.search(r'version\s+"(?P<version>[^"\s]+)', output, re.IGNORECASE)
    if not match:
        return None
    parts = match.group("version").split(".")
    if parts[0] == "1":
        return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return int(parts[0]) if parts[0].isdigit() else None


def _windows_registry_java_homes() -> list[Path]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    homes: list[Path] = []
    roots = (
        r"SOFTWARE\JavaSoft\JDK",
        r"SOFTWARE\JavaSoft\Java Development Kit",
        r"SOFTWARE\JavaSoft\JRE",
        r"SOFTWARE\JavaSoft\Java Runtime Environment",
        r"SOFTWARE\Eclipse Adoptium\JDK",
        r"SOFTWARE\AdoptOpenJDK\JDK",
        r"SOFTWARE\Microsoft\JDK",
    )
    for root in roots:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root, 0, winreg.KEY_READ | view) as key:
                    index = 0
                    while True:
                        try:
                            version = winreg.EnumKey(key, index)
                            index += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(key, version) as version_key:
                                home, _ = winreg.QueryValueEx(version_key, "JavaHome")
                                homes.append(Path(home))
                        except OSError:
                            continue
            except OSError:
                continue
    return homes


def _installation_roots() -> list[Path]:
    roots: list[Path] = []
    if sys.platform == "win32":
        drive = os.getenv("SystemDrive", "C:")
        roots.extend((Path(drive + "\\Java"), Path(drive + "\\ProgramData\\Oracle\\Java")))
        vendors = (
            "Java",
            "Eclipse Adoptium",
            "AdoptOpenJDK",
            "Microsoft",
            "Amazon Corretto",
            "BellSoft",
            "Zulu",
            "Semeru",
        )
        for base in (os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"), os.getenv("ProgramW6432")):
            if base:
                roots.extend(Path(base) / vendor for vendor in vendors)
    elif sys.platform == "darwin":
        roots.extend((Path("/Library/Java/JavaVirtualMachines"), Path.home() / "Library/Java/JavaVirtualMachines"))
    else:
        roots.extend((Path("/usr/lib/jvm"), Path("/usr/java"), Path("/opt/java"), Path.home() / ".jdks"))
    return roots


def _java_candidates() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("NEXUS_JAVA_HOME", "JAVA_HOME", "JDK_HOME"):
        if value := os.getenv(variable):
            candidates.append(_java_executable(value))
    if discovered := shutil.which("java"):
        candidates.append(Path(discovered))

    if sys.platform == "darwin":
        try:
            home = subprocess.run(
                ["/usr/libexec/java_home", "-v", str(JAVA_REQUIRED_MAJOR)],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.strip()
            if home:
                candidates.insert(0, _java_executable(home))
        except (OSError, subprocess.SubprocessError):
            pass
        candidates.extend(
            (
                Path("/opt/homebrew/opt/openjdk@21/bin/java"),
                Path("/usr/local/opt/openjdk@21/bin/java"),
            )
        )

    candidates.extend(_java_executable(home) for home in _windows_registry_java_homes())
    for root in _installation_roots():
        if not root.is_dir():
            continue
        candidates.append(_java_executable(root))
        try:
            for child in root.iterdir():
                if child.is_dir():
                    home = child / "Contents/Home" if sys.platform == "darwin" else child
                    candidates.append(_java_executable(home))
        except OSError:
            continue
    return candidates


def _select_java(candidates: Iterable[Path], required_major: int = JAVA_REQUIRED_MAJOR) -> str | None:
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.is_file():
            continue
        seen.add(key)
        if java_major(resolved) == required_major:
            return str(resolved)
    return None


def find_java_21() -> str | None:
    """Find Java 21 even if Java 8, 17, or 25 appears earlier in PATH."""
    return _select_java(_java_candidates(), JAVA_REQUIRED_MAJOR)


def find_java(required_major: int) -> str | None:
    return _select_java(_java_candidates(), required_major)


def open_in_file_manager(path: Path) -> None:
    path = path.resolve()
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
from nexus_launcher.process_utils import hidden_process_kwargs
