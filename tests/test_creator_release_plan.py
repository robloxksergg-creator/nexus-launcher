from copy import deepcopy
import pytest
from nexus_launcher.creator_release_plan import default_release_plan, validate_release_plan
from nexus_launcher.creator_services import StudioService, Capabilities
from nexus_launcher.user_instances import InstanceService


def test_legacy_and_release_intent_roundtrip(tmp_path):
    instances = InstanceService(tmp_path)
    instance = instances.create("Release", "1.21.1", "vanilla")
    studio = StudioService(instances, Capabilities("creator"))
    project = studio.load(instance.id)
    studio.check_metadata(project)
    project["releasePlan"] = dict(default_release_plan(), destination="launcher", access="PRIVATE", launcherAt="2027-01-01T12:00:00.000Z")
    studio.save(instance.id, project)
    assert studio.load(instance.id)["releasePlan"] == project["releasePlan"]
    assert not studio.capabilities.can_publish


@pytest.mark.parametrize("change", [
    {"access":"ADMIN"}, {"destination":"all"}, {"approved":True},
    {"serverAt":"2027-02-30T12:00:00.000Z"}, {"serverAt":"2027-01-01T12:00:00+06:00"},
    {"serverAt":True}, {"serverAt":"2027-01-01T12:00:30.000Z"},
    {"destination":"website","launcherAt":"2027-01-01T12:00:00.000Z"},
])
def test_invalid_plan_rejected_without_mutation(change):
    plan = dict(default_release_plan(), **change)
    original = deepcopy(plan)
    with pytest.raises(ValueError):
        validate_release_plan(plan)
    assert plan == original


@pytest.mark.parametrize("access", ["PUBLIC", "PAID", "PRIVATE"])
def test_all_access_modes_are_intent_only(access):
    plan = dict(default_release_plan(), access=access)
    assert validate_release_plan(plan) == plan
    assert not Capabilities("creator").can_publish


def test_submission_metadata_keeps_plan_without_turning_it_into_authority():
    from nexus_launcher.publishing import validate_metadata
    plan = dict(default_release_plan(), access="PAID")
    metadata = dict(title="World", shortName="World", summary="Summary", description="Description", releasePlan=plan)
    result = validate_metadata(metadata)
    assert result["releasePlan"] == plan
    assert "official" not in result and "installAllowed" not in result
    with pytest.raises(ValueError):
        validate_metadata(dict(metadata, releasePlan=dict(plan, approved=True)))
