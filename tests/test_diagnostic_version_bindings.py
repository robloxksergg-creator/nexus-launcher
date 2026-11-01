import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from nexus_launcher.instance_diagnostics import scan_instance


class VersionBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='nexus-version-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'mods').mkdir()

    def fabric(self,name,id,version,**fields):
        with zipfile.ZipFile(self.root/'mods'/name,'w') as z:
            z.writestr('fabric.mod.json',json.dumps({'schemaVersion':1,'id':id,'version':version,**fields}))

    def check(self,loader='fabric'):
        report=scan_instance(self.root,loader)
        return report, next(c for c in report.version_checks if c.dependency=='lib')

    def test_present_but_wrong_version_is_reported(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=2'})
        self.fabric('lib.jar','lib','1.9')
        r,c=self.check();self.assertEqual(c.status,'MISMATCH')
        self.assertIn('VERSION_MISMATCH',{f.code for f in r.findings})
        self.assertEqual(next(f.filename for f in r.findings if f.code=='VERSION_MISMATCH'),'a.jar')

    def test_matching_declared_version_is_scoped_to_condition(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=2 <3'})
        self.fabric('lib.jar','lib','2.1')
        r,c=self.check();self.assertEqual(c.status,'MATCH')
        self.assertNotIn('VERSION_MISMATCH',{f.code for f in r.findings})

    def test_alias_does_not_inherit_guessed_version(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        self.fabric('lib.jar','other','2',provides=['lib'])
        self.assertEqual(self.check()[1].status,'UNKNOWN')

    def test_duplicate_providers_do_not_choose_a_version(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        self.fabric('lib1.jar','lib','2');self.fabric('lib2.jar','lib','3')
        self.assertEqual(self.check()[1].status,'UNKNOWN')

    def test_partial_or_nested_inventory_is_not_green(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        self.fabric('lib.jar','lib','2',jars=[{'file':'nested.jar'}])
        self.assertEqual(self.check()[1].status,'UNKNOWN')
        self.fabric('lib.jar','lib','2');(self.root/'mods/bad.jar').write_bytes(b'not zip')
        self.assertEqual(self.check()[1].status,'UNKNOWN')

    def test_filename_and_placeholder_are_not_versions(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        self.fabric('lib-2.0.jar','lib','${file.jarVersion}')
        self.assertEqual(self.check()[1].status,'UNKNOWN')

    def test_neoforge_multi_mod_versions_keep_id_binding(self):
        with zipfile.ZipFile(self.root/'mods/bundle.jar','w') as z:
            z.writestr('META-INF/neoforge.mods.toml','''[[mods]]
modId="a"
version="1.0"
[[mods]]
modId="lib"
version="2.0"
[[dependencies.a]]
modId="lib"
type="required"
versionRange="[2,3)"
''')
        r,c=self.check('neoforge');self.assertEqual(c.actual,'2.0');self.assertEqual(c.status,'MATCH')

    def test_legacy_fabric_schema_does_not_claim_numeric_support(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        with zipfile.ZipFile(self.root/'mods/lib.jar','w') as z:z.writestr('fabric.mod.json',json.dumps({'id':'lib','version':'2'}))
        self.assertEqual(self.check()[1].status,'UNKNOWN')

    def test_runtime_versions_are_not_guessed_from_configuration(self):
        self.fabric('a.jar','a','1',depends={'minecraft':'>=1.21'})
        report=scan_instance(self.root,'fabric')
        self.assertEqual(report.version_checks[0].status,'UNKNOWN')

    def test_fabric_overrides_prevent_a_false_match(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        self.fabric('lib.jar','lib','2')
        (self.root/'config').mkdir()
        (self.root/'config/fabric_loader_dependencies.json').write_text('{}',encoding='utf8')
        self.assertEqual(self.check()[1].status,'UNKNOWN')

    def test_boolean_schema_is_not_version_one(self):
        self.fabric('a.jar','a','1',depends={'lib':'>=1'})
        self.fabric('lib.jar','lib','2',schemaVersion=True)
        self.assertEqual(self.check()[1].status,'UNKNOWN')


if __name__=='__main__':unittest.main()
