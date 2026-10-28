"""Catalog parser parity on valid profile inputs; all files are temporary."""
import json
from types import SimpleNamespace

import pytest

from nexus_launcher import native_transfer, projects


@pytest.fixture(params=["python", "rust"])
def backend(request, monkeypatch):
    if request.param == "python":
        monkeypatch.setattr(native_transfer, "_native", None)
    elif getattr(native_transfer._native, "CATALOG_API_VERSION", None) != 1:
        pytest.skip("Fresh native catalog capability unavailable")


@pytest.mark.parametrize("key", ["projects", "nexus_launcher.projects"])
@pytest.mark.parametrize("identifier", ["main", "nexus_launcher.main"])
def test_real_catalog_read_and_unknown_field_preservation(backend, tmp_path, key, identifier):
    path = tmp_path / "catalog.json"
    unknown = {"huge": 123456789012345678901234567890, "$serde_json::private::Number": "ordinary property"}
    data = [{"id": "custom", "name": "Тест", "future": unknown, "servers": [
        {"id": identifier, "address": "localhost", "java_major": 21, "future": unknown}]}]
    path.write_text(json.dumps({key: data, "unknown": unknown}, ensure_ascii=False), encoding="utf-8")
    before = path.read_bytes()
    catalog = projects.ProjectCatalog(path); result = catalog.load()
    assert result[0].servers[0].id == "main" and result[0].servers[0].java_major == 21
    assert path.read_bytes() == before
    catalog.save(result)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["unknown"] == saved["projects"][0]["future"] == unknown
    assert saved["projects"][0]["servers"][0]["future"] == unknown


@pytest.mark.parametrize("raw,accepted", [
    ('{"projects":[],"nexus_launcher.projects":[]}', True),
    ('{"projects":[{"id":"x","name":"X","extra":{"a":1,"b":2}}],"nexus_launcher.projects":[{"extra":{"b":2,"a":1},"name":"X","id":"x"}]}', True),
    ('{"projects":[{"id":"x","name":"X","extra":1e0}],"nexus_launcher.projects":[{"id":"x","name":"X","extra":1.0}]}', True),
    ('{"projects":[{"id":"x","extra":1}],"nexus_launcher.projects":[{"id":"x","extra":1.0}]}', False),
    ('{"projects":[{"id":"x","extra":true}],"nexus_launcher.projects":[{"id":"x","extra":1}]}', False),
    ('{"projects":[{"id":"x","extra":-0.0}],"nexus_launcher.projects":[{"id":"x","extra":0.0}]}', False),
    ('{"projects":[],"projects":[]}', False),
    (r'{"projects":[],"proje\u0063ts":[]}', False),
    ('{"projects":[{"id":"x","servers":[{"id":"main"},{"id":"nexus_launcher.main"}]}]}', False),
    ('{"format":99,"projects":[]}', False),
    ('{"projects":[{"id":"x","servers":[{"id":true}]}]}', False),
])
def test_dual_format_and_identity_refusals(backend, tmp_path, raw, accepted):
    path = tmp_path / "catalog.json"; path.write_text(raw, encoding="utf-8")
    before = path.read_bytes()
    if accepted:
        projects.ProjectCatalog(path).load()
    else:
        with pytest.raises(projects.CatalogConflictError): projects.ProjectCatalog(path).load()
        assert path.read_bytes() == before
        assert not path.with_suffix(".json.part").exists()


@pytest.mark.parametrize("version", [None, 99])
def test_invalid_capability_never_loads_defaults(tmp_path, monkeypatch, version):
    path = tmp_path / "catalog.json"; path.write_text('{"projects":[]}', encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(CATALOG_API_VERSION=version))
    with pytest.raises(ImportError): projects.ProjectCatalog(path).load()
    assert path.read_bytes() == before


def test_selected_native_error_retains_file_and_cause(tmp_path, monkeypatch):
    path = tmp_path / "catalog.json"; path.write_text('{"projects":[]}', encoding="utf-8")
    before = path.read_bytes(); failure = ValueError("synthetic catalog failure"); calls = []
    def fail(source): calls.append(source); raise failure
    monkeypatch.setattr(native_transfer, "_native", SimpleNamespace(
        CATALOG_API_VERSION=1, catalog_preflight_json=fail))
    with pytest.raises(projects.CatalogConflictError) as caught: projects.ProjectCatalog(path).load()
    assert caught.value.__cause__ is failure and len(calls) == 1
    assert path.read_bytes() == before and not path.with_suffix(".json.part").exists()


@pytest.mark.parametrize("raw", [
    '{"projects":[],"future":' + '[' * 130 + 'null' + ']' * 130 + '}',
    '{"projects":[],"future":NaN}',
    r'{"projects":[],"future":"\ud800"}',
])
def test_native_profile_refuses_without_writing(tmp_path, raw):
    native = native_transfer._native
    if getattr(native, "CATALOG_API_VERSION", None) != 1:
        pytest.skip("Fresh native catalog capability unavailable")
    path = tmp_path / "catalog.json"
    path.write_text(raw, encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(projects.CatalogConflictError): projects.ProjectCatalog(path).load()
    assert path.read_bytes() == before
