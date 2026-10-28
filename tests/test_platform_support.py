from pathlib import Path

import nexus_launcher.platform_support as platform_support


def test_java_major_understands_legacy_java_8(monkeypatch):
    class Result:
        stderr = 'java version "1.8.0_481"'
        stdout = ""

    monkeypatch.setattr(platform_support.subprocess, "run", lambda *args, **kwargs: Result())
    assert platform_support.java_major("java") == 8


def test_java_major_understands_java_21(monkeypatch):
    class Result:
        stderr = 'openjdk version "21.0.11" 2026-04-21 LTS'
        stdout = ""

    monkeypatch.setattr(platform_support.subprocess, "run", lambda *args, **kwargs: Result())
    assert platform_support.java_major("java") == 21


def test_selector_skips_java_8_and_chooses_java_21(tmp_path, monkeypatch):
    java8 = tmp_path / "jdk-8" / "bin" / "java.exe"
    java21 = tmp_path / "jdk-21" / "bin" / "java.exe"
    java8.parent.mkdir(parents=True)
    java21.parent.mkdir(parents=True)
    java8.touch()
    java21.touch()

    monkeypatch.setattr(platform_support, "java_major", lambda path: 21 if Path(path) == java21 else 8)
    assert platform_support._select_java([java8, java21]) == str(java21.resolve())
