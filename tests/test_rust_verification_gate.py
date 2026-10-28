"""Test the verification harness preconditions, not the native implementation."""
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

gate = runpy.run_path(str(Path(__file__).resolve().parents[1] / "packaging/verify_rust_core.py"))


def fake_extension(path):
    return SimpleNamespace(__file__=str(path), **gate["CAPABILITIES"],
                           **{name: lambda: None for name in gate["ENTRYPOINTS"]})


@pytest.mark.parametrize("name", list(gate["CAPABILITIES"]))
def test_old_or_incompatible_extension_is_rejected(tmp_path, name):
    path = tmp_path / "fake.pyd"
    path.write_bytes(b"synthetic fixture, not a DLL")
    module = fake_extension(path)
    delattr(module, name)
    with pytest.raises(RuntimeError, match=name):
        gate["check_extension"](module, path)
    setattr(module, name, 99)
    with pytest.raises(RuntimeError, match=name):
        gate["check_extension"](module, path)


def test_wrong_import_origin_is_rejected(tmp_path):
    module = fake_extension(tmp_path / "wrong.pyd")
    with pytest.raises(RuntimeError, match="unexpected location"):
        gate["check_extension"](module, tmp_path / "expected.pyd")


@pytest.mark.parametrize("name", list(gate["ENTRYPOINTS"]))
def test_noncallable_entrypoint_is_rejected(tmp_path, name):
    path = tmp_path / "fake.pyd"
    module = fake_extension(path)
    setattr(module, name, None)
    with pytest.raises(RuntimeError, match=name):
        gate["check_extension"](module, path)


def test_reports_distinguish_assertions_errors_and_skips():
    observer = gate["Results"]()
    def report(when="call", outcome="passed", subtest=False):
        values = dict(when=when, passed=outcome == "passed", failed=outcome == "failed",
                      skipped=outcome == "skipped")
        if subtest:
            values["context"] = object()
        return SimpleNamespace(**values)
    observer.pytest_runtest_logreport(report())
    observer.pytest_runtest_logreport(report(outcome="passed", subtest=True))
    observer.pytest_runtest_logreport(report(when="setup", outcome="skipped"))
    observer.pytest_runtest_logreport(report(when="teardown", outcome="failed"))
    observer.pytest_collectreport(report(outcome="failed"))
    assert observer.counts == dict(passed=1, failed=0, skipped=1, errors=2, subtests_passed=1)


def test_snapshot_detects_edits_and_additions(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("old", encoding="utf-8")
    before = gate["snapshot"](tmp_path)
    source.write_text("new", encoding="utf-8")
    (tmp_path / "added.py").write_text("new", encoding="utf-8")
    after = gate["snapshot"](tmp_path)
    assert before["source.py"] != after["source.py"]
    assert set(after) - set(before) == {"added.py"}
