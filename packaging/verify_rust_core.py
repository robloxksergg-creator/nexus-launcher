"""Verify a freshly built Windows extension; missing capabilities/skips fail closed.

Does not build, install, download, or launch the application. Reports and the
extension must live outside the checkout; tests use only their owned temp files.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = {name: 1 for name in (
    "CORE_API_VERSION", "HTTP_API_VERSION", "TRANSACTION_API_VERSION",
    "SAFE_IO_API_VERSION", "HANDLE_REPLACE_API_VERSION", "COPY_STREAM_API_VERSION",
    "ARCHIVE_API_VERSION",
    "STREAM_IO_API_VERSION",
    "STREAM_HASH_API_VERSION",
    "ZIP_DEFLATE_API_VERSION",
    "ZIP_ENCODE_API_VERSION",
    "ZIP_LIMITS_API_VERSION",
    "LAUNCH_POLICY_API_VERSION",
    "CATALOG_API_VERSION",
    "MINECRAFT_COMMAND_API_VERSION",
    "MINECRAFT_PROFILE_API_VERSION",
    "MINECRAFT_CLASSPATH_API_VERSION",
    "MINECRAFT_RULES_API_VERSION",
)}
ENTRYPOINTS = (
    "TransferVerifier", "DownloadClient", "WindowsDirectoryPin",
    "windows_replace_file", "windows_copy_streams", "transaction_apply", "transaction_recover",
    "archive_inventory",
    "stream_read_limited", "stream_copy_limited",
    "stream_digest_limited",
    "ZipDeflateDecoder",
    "ZipDeflateEncoder",
    "catalog_preflight_json",
    "minecraft_compose_command",
    "minecraft_inherit_profile",
    "minecraft_classpath_entries",
    "minecraft_rules_evaluate",
    "launch_username_valid", "launch_environment_mask", "launch_redact_command",
)
TESTS = (
    "test_native_copy.py", "test_native_replace.py", "test_native_safe_io.py",
    "test_windows_pinning.py", "test_native_transaction.py", "test_file_transaction.py",
    "test_updater.py", "test_native_transfer.py", "test_native_http.py", "test_rust_verification_gate.py",
    "test_native_archive.py",
    "test_native_stream_io.py", "test_release_deadlines.py", "test_instance_transfer.py",
    "test_native_stream_hash.py",
    "test_native_zip.py",
    "test_native_zip_encode.py",
    "test_native_minecraft_command.py",
    "test_native_minecraft_profile.py",
    "test_native_minecraft_classpath.py",
    "test_native_minecraft_rules.py",
    "test_native_catalog.py",
    "test_catalog_compatibility.py", "test_projects.py", "test_config_recovery.py",
    "test_native_launch_policy.py",
    "test_game_environment.py::test_game_does_not_inherit_service_secrets_or_vm_injection",
    "test_game_environment.py::test_secret_values_are_not_even_read_from_input_mapping",
    "test_native_inventory_hash.py", "test_build_management.py", "test_curseforge_importer.py",
    "test_native_publishing_zip.py",
    "test_native_publishing_hash.py", "test_functional_pass6.py",
    "test_creator_services.py::test_classified_export_and_changes",
)


def check_extension(module, expected: Path) -> dict:
    if Path(module.__file__).resolve() != expected.resolve():
        raise RuntimeError("Extension was imported from an unexpected location")
    for name, version in CAPABILITIES.items():
        if getattr(module, name, None) != version:
            raise RuntimeError(f"Missing/incompatible native capability: {name}")
    for name in ENTRYPOINTS:
        if not callable(getattr(module, name, None)):
            raise RuntimeError(f"Missing native entrypoint: {name}")
    return {"path": str(expected), "sha256": hashlib.sha256(expected.read_bytes()).hexdigest(),
            "capabilities": dict(CAPABILITIES)}


def snapshot(root: Path) -> dict[str, str]:
    result = {}
    for folder, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in {
            ".git", "__pycache__", ".pytest_cache", ".ruff_cache",
        }]
        for name in files:
            path = Path(folder) / name
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class Results:
    def __init__(self):
        self.counts = {key: 0 for key in ("passed", "failed", "skipped", "errors", "subtests_passed")}

    def pytest_runtest_logreport(self, report):
        if hasattr(report, "context"):
            if report.passed:
                self.counts["subtests_passed"] += 1
            elif report.failed:
                self.counts["failed"] += 1
            elif report.skipped:
                self.counts["skipped"] += 1
        elif report.skipped:
            self.counts["skipped"] += 1
        elif report.when == "call":
            self.counts["passed" if report.passed else "failed"] += 1
        elif report.failed:
            self.counts["errors"] += 1

    def pytest_collectreport(self, report):
        if report.failed:
            self.counts["errors"] += 1
        elif report.skipped:
            self.counts["skipped"] += 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extension-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    extension_dir, results_dir = args.extension_dir.resolve(), args.results_dir.resolve()
    if extension_dir.is_relative_to(ROOT) or results_dir.is_relative_to(ROOT):
        parser.error("Extension and reports must be outside the repository")
    results_dir.mkdir(parents=True, exist_ok=False)
    before = snapshot(ROOT)
    result = {"status": "BLOCKED", "python": sys.version, "tests": list(TESTS)}
    code = 2
    try:
        if os.name != "nt":
            raise RuntimeError("This verification requires Windows handle semantics")
        sys.dont_write_bytecode = True
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        os.environ["PYTHONPATH"] = os.pathsep.join((str(extension_dir), str(ROOT)))
        sys.path[:0] = [str(extension_dir), str(ROOT)]
        module = importlib.import_module("_nexus_launcher_core")
        result["extension"] = check_extension(module, extension_dir / "_nexus_launcher_core.pyd")
        import pytest

        observer = Results()
        code = int(pytest.main([
            *(str(ROOT / "tests" / name) for name in TESTS), "-q", "-p", "no:cacheprovider",
            "--tb=short", f"--junitxml={results_dir / 'tests.xml'}",
        ], plugins=[observer]))
        result["pytest_exit_code"] = code
        result["counts"] = observer.counts
        if observer.counts["skipped"] or observer.counts["errors"] or observer.counts["failed"]:
            code = code or 1
        if observer.counts["passed"] == 0:
            code = code or 1
        result["status"] = "PASS" if code == 0 else "FAIL"
    except Exception as error:
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        after = snapshot(ROOT)
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        result["changed_checkout_files"] = changed
        if changed:
            code = code or 1
            result["status"] = "FAIL"
        result["exit_code"] = code
        (results_dir / "verification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
