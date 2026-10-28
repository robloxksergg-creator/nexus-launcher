import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest

from nexus_launcher.creator_services import Capabilities
from nexus_launcher.publishing import (BundledCatalogueRepository, LocalSubmissionRepository, PublicationState, PublishingService,
                        ReviewRecord, Submission, SubmissionPackage, normalize_tags, safe_slug,
                        validate_metadata)


def metadata(**changes):
    value = {"title": "My World", "shortName": "MW", "summary": "Summary", "description": "Description",
             "category": "RPG", "tags": ["Create", "SMP"], "language": "ru", "channel": "dev",
             "visibility": "private"}
    value.update(changes)
    return value


def submission(identifier="11111111-1111-1111-1111-111111111111", revision=1):
    return Submission(identifier, "project", "creator", revision, "1.2.3", "1.21.1", "neoforge",
                      validate_metadata(metadata()), {}, "artifacts/client.zip", manifest_summary={"files": 1},
                      created_at=1, status=PublicationState.READY_FOR_SUBMISSION,
                      review_history=(ReviewRecord("creator", "package_prepared", 1),))


def artifact(path: Path, executable=False):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mods/a.jar", b"mod")
        if executable:
            archive.writestr("scripts/run.ps1", b"never execute")


def test_publication_state_and_roles_are_separate():
    assert PublicationState.LOCAL_DRAFT != PublicationState.PUBLISHED
    assert Capabilities("creator").can_prepare_submission
    assert not Capabilities("creator").can_review_submission
    assert not Capabilities("reviewer").can_review_submission
    assert Capabilities("reviewer", True).can_review_submission
    assert not Capabilities("reviewer", True).can_publish


def test_metadata_tags_slug_and_trust_boundary():
    assert safe_slug("My RPG World") == "my-rpg-world"
    assert normalize_tags("create, Aeronautics, create") == ["Create", "Aeronautics"]
    with pytest.raises(PermissionError):
        validate_metadata(metadata(official=True))
    with pytest.raises(ValueError):
        validate_metadata(metadata(website="file:///secret"))
    with pytest.raises(ValueError):
        normalize_tags(["x"] * 13)


def test_create_reopen_and_validate_submission_package(tmp_path):
    client = tmp_path / "client.zip"
    artifact(client)
    package = tmp_path / "world.nexus-submission"
    SubmissionPackage.create(package, submission(), client)
    loaded, warnings = SubmissionPackage.inspect(package)
    assert loaded.project_id == "project"
    assert loaded.client_artifact == "artifacts/client.zip"
    assert warnings == []
    raw = package.read_bytes()
    assert str(tmp_path).encode() not in raw


def test_executable_is_review_warning_and_never_executed(tmp_path):
    client = tmp_path / "client.zip"
    artifact(client, executable=True)
    package = tmp_path / "world.nexus-submission"
    SubmissionPackage.create(package, submission(), client)
    _loaded, warnings = SubmissionPackage.inspect(package)
    assert any("scripts/run.ps1" in warning for warning in warnings)


def test_corrupt_artifact_hash_is_rejected(tmp_path):
    client = tmp_path / "client.zip"
    artifact(client)
    package = tmp_path / "world.nexus-submission"
    SubmissionPackage.create(package, submission(), client)
    rewritten = tmp_path / "corrupt.nexus-submission"
    with zipfile.ZipFile(package) as source, zipfile.ZipFile(rewritten, "w") as target:
        for info in source.infolist():
            data = source.read(info)
            target.writestr(info.filename, b"corrupt" if info.filename == "artifacts/client.zip" else data)
    with pytest.raises(ValueError, match="hash mismatch"):
        SubmissionPackage.inspect(rewritten)


def test_secret_absolute_path_and_fake_official_are_rejected(tmp_path):
    client = tmp_path / "client.zip"; artifact(client)
    package = tmp_path / "world.nexus-submission"; SubmissionPackage.create(package, submission(), client)
    for key, value in (("owner", "C:\\Users\\Creator"), ("official", True), ("authToken", "secret-value")):
        bad = tmp_path / f"bad-{key}.nexus-submission"
        with zipfile.ZipFile(package) as source, zipfile.ZipFile(bad, "w") as target:
            for info in source.infolist():
                data = source.read(info)
                if info.filename == "submission.json":
                    raw = json.loads(data); raw[key] = value; data = json.dumps(raw).encode()
                target.writestr(info.filename, data)
        with pytest.raises((ValueError, PermissionError)):
            SubmissionPackage.inspect(bad)


def test_review_permissions_history_revision_withdraw_and_candidate(tmp_path):
    repository = LocalSubmissionRepository(tmp_path / "repo")
    original = repository.save(submission())
    assert repository.next_revision("project") == 2
    with pytest.raises(PermissionError):
        repository.review(original.id, "approve", "creator", reviewer=False)
    changed = repository.review(original.id, "request_changes", "reviewer", "Replace poster", reviewer=True)
    assert changed.status == PublicationState.CHANGES_REQUESTED
    assert changed.review_history[-1].comment == "Replace poster"
    with pytest.raises(PermissionError):
        repository.save(replace(changed, review_history=()))
    approved = repository.review(original.id, "approve", "reviewer", reviewer=True)
    candidate = repository.approved_candidate(approved.id, "reviewer", reviewer=True)
    assert candidate["signed"] is False and candidate["official"] is False
    assert candidate["status"] == PublicationState.RELEASE_CANDIDATE
    withdrawn = repository.withdraw(original.id, "creator")
    assert withdrawn.status == PublicationState.WITHDRAWN


def test_catalogue_repository_does_not_mix_local_projects():
    worlds = [{"id": "gearmorph", "trust": "official"}]
    repository = BundledCatalogueRepository(worlds)
    assert repository.list_worlds() == worlds
    worlds.append({"id": "local-project"})
    assert repository.list_worlds() != worlds


def test_prepare_pipeline_builds_portable_reopenable_revision(tmp_path):
    from types import SimpleNamespace
    from nexus_launcher.creator_services import ValidationIssue

    root = tmp_path / "instance"
    (root / "mods").mkdir(parents=True)
    (root / "mods" / "a.jar").write_bytes(b"jar")
    icon = tmp_path / "icon.png"; icon.write_bytes(b"png")
    banner = tmp_path / "banner.png"; banner.write_bytes(b"png")

    class Instances:
        def load(self, _identifier): return SimpleNamespace(minecraft_version="1.21.1", loader="neoforge")
        def path_for(self, _identifier): return root

    class Studio:
        instances = Instances()
        def load(self, _identifier):
            return {"name": "My World", "version": "1.0.0", "description": "A complete world description",
                    "channel": "dev", "changelog": "First candidate", "presentation": {"icon": str(icon), "banner": str(banner)},
                    "metadata": {"short_name": "MW", "summary": "A world", "category": "RPG", "tags": "SMP"}}
        def validation_report(self, _identifier, _server): return [ValidationIssue("INFO", "valid")]
        def export(self, _identifier, destination, _server):
            artifact(destination)
            return destination
        def inventory(self, _identifier): return {"mods/a.jar": "a" * 64}

    repository = LocalSubmissionRepository(tmp_path / "repo")
    package = tmp_path / "candidate.nexus-submission"
    prepared = PublishingService(Studio(), repository, Capabilities("creator")).prepare("project", package)
    reopened, warnings = SubmissionPackage.inspect(package)
    assert prepared.revision == reopened.revision == 1
    assert reopened.status == PublicationState.READY_FOR_SUBMISSION
    assert reopened.manifest_summary["hashAlgorithm"] == "SHA-256"
    assert warnings == []
