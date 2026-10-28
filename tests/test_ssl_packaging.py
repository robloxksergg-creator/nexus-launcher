from pathlib import Path
import runpy

import pytest


HOOK = Path(__file__).resolve().parents[1] / 'packaging/hooks/hook-ssl.py'


def test_supplemental_policy_is_collected_without_changes(tmp_path, monkeypatch):
    source = tmp_path / 'ssl.py'; source.write_text('load("codex-rejected-cas.pem")')
    policy = tmp_path / 'codex-rejected-cas.pem'; payload = b'synthetic policy bytes'; policy.write_bytes(payload)
    monkeypatch.setattr('PyInstaller.utils.hooks.get_module_file_attribute', lambda name: str(source))
    assert runpy.run_path(str(HOOK))['datas'] == [(str(policy), '.')]
    assert policy.read_bytes() == payload


def test_referenced_missing_policy_fails_build(tmp_path, monkeypatch):
    source = tmp_path / 'ssl.py'; source.write_text('load("codex-rejected-cas.pem")')
    monkeypatch.setattr('PyInstaller.utils.hooks.get_module_file_attribute', lambda name: str(source))
    with pytest.raises(RuntimeError, match='policy file is missing'):
        runpy.run_path(str(HOOK))


def test_standard_interpreter_needs_no_extra_policy(tmp_path, monkeypatch):
    source = tmp_path / 'ssl.py'; source.write_text('class SSLContext: pass')
    monkeypatch.setattr('PyInstaller.utils.hooks.get_module_file_attribute', lambda name: str(source))
    assert runpy.run_path(str(HOOK))['datas'] == []


def test_portable_spec_enables_ssl_hook():
    spec = HOOK.parents[1] / 'specs/NexusPortable.spec'
    assert 'hookspath=[str(root / "packaging" / "hooks")]' in spec.read_text(encoding='utf-8')
