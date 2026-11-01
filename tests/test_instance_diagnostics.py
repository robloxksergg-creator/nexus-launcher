"""Synthetic metadata and crash fixtures; never execute a JAR or alter a pack."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from nexus_launcher.instance_diagnostics import scan_instance, analyze_crash, redact


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nexus-diagnostics-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'mods').mkdir()

    def jar(self, name, value, member='fabric.mod.json'):
        path = self.root/'mods'/name
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr(member, json.dumps(value) if isinstance(value, dict) else value)
        return path

    def codes(self, report):
        return {x.code for x in report.findings}

    def test_declared_dependency_and_alias_do_not_claim_version_compatibility(self):
        self.jar('a.jar', {'id':'a','depends':{'lib':'>=99','minecraft':'>=1.0','fabricloader':'*'}})
        self.jar('b.jar', {'id':'b','provides':['lib']})
        r = scan_instance(self.root,'fabric')
        self.assertTrue(r.complete)
        self.assertNotIn('MISSING_DEPENDENCY',self.codes(r))
        self.assertEqual(r.mods[0].requires[0],('fabricloader','"*"'))
        self.assertIn('LIMITATIONS',self.codes(r))

    def test_missing_required_dependency(self):
        self.jar('a.jar',{'id':'a','depends':{'missing':'>=2'}})
        f=next(x for x in scan_instance(self.root,'fabric').findings if x.code=='MISSING_DEPENDENCY')
        self.assertEqual(f.filename,'a.jar')
        self.assertEqual(f.evidence,('a.jar','missing','">=2"'))

    def test_duplicate_ids_and_loader_mismatch(self):
        self.jar('a.jar',{'id':'same'})
        self.jar('b.jar',{'id':'same'})
        codes=self.codes(scan_instance(self.root,'neoforge'))
        self.assertIn('DUPLICATE_ID',codes)
        self.assertIn('LOADER_MISMATCH',codes)

    def test_nested_jars_do_not_establish_missing_dependency(self):
        self.jar('a.jar',{'id':'a','jars':[{'file':'nested.jar'}],'depends':{'hidden':'*'}})
        codes=self.codes(scan_instance(self.root,'fabric'))
        self.assertIn('UNRESOLVED_DEPENDENCY',codes)
        self.assertNotIn('MISSING_DEPENDENCY',codes)

    def test_unreadable_jar_makes_report_incomplete(self):
        self.jar('a.jar',{'id':'a','depends':{'hidden':'*'}})
        (self.root/'mods/b.jar').write_bytes(b'NOT A ZIP')
        r=scan_instance(self.root,'fabric')
        self.assertFalse(r.complete)
        self.assertIn('UNREADABLE_MOD',self.codes(r))
        self.assertIn('UNRESOLVED_DEPENDENCY',self.codes(r))

    def test_disabled_mod_is_not_an_enabled_dependency(self):
        self.jar('a.jar',{'id':'a','depends':{'b':'*'}})
        p=self.jar('b.jar',{'id':'b'})
        (self.root/'disabled_mods').mkdir()
        p.rename(self.root/'disabled_mods/b.jar')
        self.assertIn('MISSING_DEPENDENCY',self.codes(scan_instance(self.root,'fabric')))

    def test_forge_required_optional_and_server_dependencies(self):
        value='''[[mods]]
modId="forge_a"
[[dependencies.forge_a]]
modId="required"
mandatory=true
versionRange="[2,)"
[[dependencies.forge_a]]
modId="optional"
mandatory=false
[[dependencies.forge_a]]
modId="server_only"
mandatory=true
side="SERVER"
'''
        self.jar('forge.jar',value,'META-INF/mods.toml')
        r=scan_instance(self.root,'forge')
        self.assertEqual(r.mods[0].requires,(('required','[2,)'),))

    def test_duplicate_json_metadata_is_not_trusted(self):
        self.jar('a.jar','{"id":"a","id":"b"}')
        self.assertFalse(scan_instance(self.root,'fabric').complete)

    def test_metadata_and_scan_limits(self):
        self.jar('a.jar',{'id':'a'})
        with patch('nexus_launcher.instance_diagnostics.MAX_METADATA',4):
            self.assertIn('UNREADABLE_MOD',self.codes(scan_instance(self.root,'fabric')))
        self.jar('b.jar',{'id':'b'})
        with patch('nexus_launcher.instance_diagnostics.MAX_MODS',1):
            r=scan_instance(self.root,'fabric')
            self.assertFalse(r.complete)
            self.assertIn('SCAN_LIMIT',self.codes(r))

    def test_cancellation_is_incomplete(self):
        self.jar('a.jar',{'id':'a'})
        self.assertFalse(scan_instance(self.root,'fabric',lambda:True).complete)

    def test_explicit_reported_mod_is_candidate_not_cause(self):
        self.jar('a.jar',{'id':'a'})
        directory=self.root/'crash-reports';directory.mkdir()
        (directory/'crash.txt').write_text('Mod ID: a\njava.lang.OutOfMemoryError: Java heap space\n',encoding='utf8')
        r=scan_instance(self.root,'fabric')
        self.assertEqual(r.crash_file,'crash.txt')
        self.assertIn('OUT_OF_MEMORY',self.codes(r))
        self.assertEqual(next(x for x in r.findings if x.code=='REPORTED_MOD').filename,'a.jar')

    def test_generic_stack_frame_does_not_blame_mod(self):
        findings=analyze_crash('at a.some.Class.run(Class.java:1)\nExit code: 1',[],'crash.txt')
        self.assertEqual(findings[0].code,'CRASH_UNKNOWN')
        self.assertEqual(redact('Bearer abc.def.ghi --accessToken secret-value'),'Bearer [REDACTED] --accessToken [REDACTED]')

    def test_scan_never_changes_inputs(self):
        self.jar('a.jar',{'id':'a'})
        (self.root/'options.txt').write_bytes(b'keep settings')
        before={p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        scan_instance(self.root,'fabric')
        after={p.relative_to(self.root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_unknown_loader_does_not_confirm_missing_runtime(self):
        self.jar('a.jar',{'id':'a','depends':{'fabricloader':'*'}})
        self.assertIn('UNRESOLVED_DEPENDENCY',self.codes(scan_instance(self.root,'quilt')))

    def test_missing_instance_is_not_an_empty_healthy_pack(self):
        with self.assertRaises(FileNotFoundError):
            scan_instance(self.root/'absent','fabric')


if __name__=='__main__':
    unittest.main()
