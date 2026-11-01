"""Owned temporary files only. No game, external account or launch."""
from contextlib import nullcontext
import hashlib
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from nexus_launcher.diagnostic_trial import DiagnosticTrials, TrialError, launcher_idle
from nexus_launcher.user_instances import InstanceService, InstalledMod


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nexus-trial-test-')
        self.addCleanup(self.temp.cleanup)
        self.service=InstanceService(Path(self.temp.name)/'instances')
        self.source=self.service.create('Original','1.21.1','fabric','0.16.10')
        self.root=self.service.path_for(self.source.id)
        (self.root/'mods/a.jar').write_bytes(b'SYNTHETIC JAR; NEVER EXECUTE')
        (self.root/'config/keep.cfg').write_bytes(b'original settings')
        (self.root/'saves/world').mkdir()
        (self.root/'saves/world/level.dat').write_bytes(b'synthetic world')
        self.source.installed_mods=[InstalledMod('local:a','v1','A','a.jar',hashlib.sha512((self.root/'mods/a.jar').read_bytes()).hexdigest())]
        self.service.save(self.source)
        # nullcontext is fixture-only; production supplies the launcher's guard.
        self.trials=DiagnosticTrials(self.service,self.source.id,nullcontext)

    def hashes(self):
        return {p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}

    def test_prepare_is_read_only_and_copy_preserves_original(self):
        before=self.hashes()
        plan=self.trials.prepare('a.jar')
        self.assertEqual(before,self.hashes())
        self.assertFalse((self.service.root/'.diagnostic-staging').exists())
        result=self.trials.apply(plan)
        self.assertEqual(before,self.hashes())
        self.assertEqual(result.source_id,self.source.id)
        target=self.service.path_for(result.trial_id)
        self.assertFalse((target/'mods/a.jar').exists())
        self.assertEqual((target/'disabled_mods/a.jar').read_bytes(),(self.root/'mods/a.jar').read_bytes())
        self.assertEqual((target/'saves/world/level.dat').read_bytes(),b'synthetic world')
        self.assertFalse(self.service.load(result.trial_id).installed_mods[0].enabled)
        self.assertTrue(self.service.load(self.source.id).installed_mods[0].enabled)
        self.assertEqual({x.id for x in self.service.list()},{self.source.id,result.trial_id})

    def test_changed_source_rejects_stale_plan(self):
        plan=self.trials.prepare('a.jar')
        (self.root/'config/keep.cfg').write_bytes(b'new settings')
        with self.assertRaises(TrialError):self.trials.apply(plan)
        self.assertFalse(self.service.path_for(plan.trial_id).exists())

    def test_existing_disabled_name_is_never_replaced(self):
        (self.root/'disabled_mods/a.jar').write_bytes(b'KEEP OTHER COPY')
        with self.assertRaises(TrialError):self.trials.prepare('a.jar')
        self.assertEqual((self.root/'disabled_mods/a.jar').read_bytes(),b'KEEP OTHER COPY')

    def test_existing_target_is_never_replaced(self):
        plan=self.trials.prepare('a.jar')
        target=self.service.path_for(plan.trial_id);target.mkdir()
        (target/'keep.txt').write_bytes(b'KEEP TARGET')
        with self.assertRaises(TrialError):self.trials.apply(plan)
        self.assertEqual((target/'keep.txt').read_bytes(),b'KEEP TARGET')

    def test_copy_error_cleans_only_owned_staging(self):
        plan=self.trials.prepare('a.jar');before=self.hashes()
        with patch('nexus_launcher.diagnostic_trial.atomic_copy',side_effect=OSError('synthetic copy failure')):
            with self.assertRaises(OSError):self.trials.apply(plan)
        self.assertEqual(before,self.hashes())
        self.assertFalse(self.service.path_for(plan.trial_id).exists())
        self.assertFalse((self.service.root/'.diagnostic-staging'/plan.trial_id).exists())

    def test_cancelled_copy_does_not_publish(self):
        plan=self.trials.prepare('a.jar')
        with self.assertRaises(TrialError):self.trials.apply(plan,lambda:True)
        self.assertFalse(self.service.path_for(plan.trial_id).exists())

    def test_guard_denial_performs_no_copy(self):
        owner=SimpleNamespace(_launch_lock=threading.Lock(),game_process=None)
        owner._launch_lock.acquire()
        trials=DiagnosticTrials(self.service,self.source.id,lambda:launcher_idle(owner))
        try:
            with self.assertRaises(TrialError):trials.prepare('a.jar')
        finally:owner._launch_lock.release()
        self.assertFalse((self.service.root/'.diagnostic-staging').exists())

    def test_owned_live_process_blocks_and_releases_guard(self):
        owner=SimpleNamespace(_launch_lock=threading.Lock(),game_process=SimpleNamespace(poll=lambda:None))
        with self.assertRaises(TrialError):
            with launcher_idle(owner):pass
        self.assertFalse(owner._launch_lock.locked())

    def test_guard_is_held_for_operation_then_released(self):
        owner=SimpleNamespace(_launch_lock=threading.Lock(),game_process=None)
        with launcher_idle(owner):self.assertTrue(owner._launch_lock.locked())
        self.assertFalse(owner._launch_lock.locked())

    def test_no_source_discovery_writes_and_cache_is_not_cloned(self):
        (self.root/'mods/unregistered.jar').write_bytes(b'unknown local file')
        (self.root/'.nexus/cache/downloads/keep.part').write_bytes(b'cache')
        before=self.hashes()
        result=self.trials.apply(self.trials.prepare('a.jar'))
        self.assertEqual(before,self.hashes())
        target=self.service.path_for(result.trial_id)
        self.assertFalse((target/'.nexus/cache/downloads/keep.part').exists())
        self.assertEqual((target/'mods/unregistered.jar').read_bytes(),b'unknown local file')

    def test_managed_instance_is_not_eligible(self):
        self.source.instance_type='managed';self.service.save(self.source)
        with self.assertRaises(TrialError):self.trials.prepare('a.jar')

    def test_invalid_filename_is_refused(self):
        for filename in ('../a.jar','a.txt','/a.jar'):
            with self.assertRaises(ValueError):self.trials.prepare(filename)


if __name__=='__main__':
    unittest.main()
