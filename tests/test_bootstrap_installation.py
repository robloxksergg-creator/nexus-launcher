import json
from datetime import UTC, datetime, timedelta

import pytest

from nexus_launcher.bootstrap_installation import provision_initial
from nexus_launcher.portable_transition import prepare_transition, resolve_transition
from tests.test_portable_package import fixture, resign
from tests.test_portable_transition import environment


def initial(tmp_path):
    archive, envelope, keys, key = fixture()
    envelope['release'].update(available=True, platform='windows', arch='x64')
    resign(envelope, key)
    source = tmp_path/'fixture.zip'
    source.write_bytes(archive.getvalue())
    return tmp_path/'install', source, envelope, keys


def test_initial_signed_package_and_idempotent_installed_pointer(tmp_path):
    root, source, envelope, keys = initial(tmp_path)
    assert provision_initial(root, source, envelope, platform='windows', arch='x64', keys=keys)
    before = (root/'active.json').read_bytes()
    assert not provision_initial(root, source, envelope, platform='windows', arch='x64', keys=keys)
    assert (root/'active.json').read_bytes() == before
    assert json.loads((root/'initial-provision.json').read_text())['phase'] == 'COMPLETE'


@pytest.mark.parametrize('fault', ['highest-package.json', 'active.json'])
def test_initial_power_loss_resumes_exact_signed_receipt(tmp_path, monkeypatch, fault):
    import nexus_launcher.bootstrap_installation as module
    root, source, envelope, keys = initial(tmp_path)
    actual = module.atomic_json
    def fail(path, value):
        if path.name == fault:
            raise OSError('synthetic write fault')
        actual(path, value)
    with monkeypatch.context() as patch:
        patch.setattr(module, 'atomic_json', fail)
        with pytest.raises(OSError):
            provision_initial(root, source, envelope, platform='windows', arch='x64', keys=keys)
    assert not (root/'active.json').exists()
    assert provision_initial(root, source, envelope, platform='windows', arch='x64', keys=keys)
    assert len(list((root/'slots').iterdir())) == 1


def test_missing_installed_pointer_cannot_be_recreated_as_first_install(tmp_path):
    root, source, envelope, keys = initial(tmp_path)
    root.mkdir()
    (root/'highest-package.json').write_text('{}')
    with pytest.raises(ValueError, match='missing'):
        provision_initial(root, source, envelope, platform='windows', arch='x64', keys=keys)


def test_expired_installed_previous_slot_can_update_and_rollback_without_bypassing_signature(tmp_path):
    root, old, new, keys, _, key, _ = environment(tmp_path)
    envelope = json.loads((old/'envelope.json').read_text())
    envelope['release']['expires_at'] = (datetime.now(UTC)-timedelta(seconds=1)).isoformat()
    resign(envelope, key)
    (old/'envelope.json').write_text(json.dumps(envelope))
    journal = prepare_transition(root, new.name, old.name, platform='windows', arch='x64', keys=keys)
    result = resolve_transition(root, 'FAILED', operation_id=journal['operation_id'],
                                candidate_identity=journal['candidate_identity'], keys=keys)
    assert result['phase'] == 'ROLLED_BACK'
    envelope['release']['version'] = '0.0.0'  # invalid signature must still fail
    (old/'envelope.json').write_text(json.dumps(envelope))
    with pytest.raises(ValueError):
        prepare_transition(root, new.name, old.name, platform='windows', arch='x64', keys=keys)
