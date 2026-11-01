"""Synthetic nested JAR inventory; no class loading or extraction."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import warnings
from unittest.mock import patch
import zipfile

from nexus_launcher.instance_diagnostics import inspect_nested, scan_instance


def jar(metadata, members=()):
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('fabric.mod.json', json.dumps(metadata))
        for name, content in members:
            archive.writestr(name, content)
    return output.getvalue()


class NestedDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='nexus-nested-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'mods').mkdir()
        self.path = self.root / 'mods' / 'outer.jar'

    def write(self, declarations, members=()):
        self.path.write_bytes(jar({'id': 'outer', 'version': '1', 'schemaVersion': 1,
                                   'jars': declarations, 'depends': {'lib': '*'}}, members))

    def read(self):
        return inspect_nested(self.path, lambda size: None, [0, 0])

    def test_candidate_provenance_does_not_resolve_dependency(self):
        self.write([{'file': 'libs/lib.jar'}], [('libs/lib.jar', jar({'id': 'lib', 'version': '2', 'schemaVersion': 1}))])
        before = self.path.read_bytes()
        report = scan_instance(self.root, 'fabric')
        candidate = next(x for x in report.findings if x.code == 'NESTED_CANDIDATE')
        self.assertEqual(candidate.evidence, ('outer.jar ! libs/lib.jar',))
        self.assertIn('lib@2', candidate.detail)
        self.assertEqual(len(report.mods), 1)
        self.assertEqual(report.version_checks[0].status, 'UNKNOWN')
        self.assertIn('UNRESOLVED_DEPENDENCY', {x.code for x in report.findings})
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['mods'])

    def test_missing_corrupt_and_ambiguous_members(self):
        for members in [[], [('lib.jar', b'not zip')], [('lib.jar', b'a'), ('lib.jar', b'b')]]:
            with self.subTest(members=len(members)), warnings.catch_warnings():
                warnings.simplefilter('ignore', UserWarning)
                self.write([{'file': 'lib.jar'}], members)
                self.assertTrue(all(x[0] == 'UNKNOWN' for x in self.read()))

    def test_unsafe_paths_and_duplicate_declarations(self):
        for name in ['../lib.jar', '/lib.jar', 'C:/lib.jar', 'a\\lib.jar', 'a//lib.jar', 'a/./lib.jar']:
            with self.subTest(name=name):
                self.write([{'file': name}])
                self.assertEqual(self.read()[0][0], 'UNKNOWN')
        self.write([{'file': 'lib.jar'}, {'file': 'lib.jar'}])
        self.assertTrue(any(x[0] == 'UNKNOWN' for x in self.read()))

    def test_depth_limit(self):
        content = jar({'id': 'leaf'})
        for index in range(5):
            content = jar({'id': 'node', 'jars': [{'file': 'next.jar'}]}, [('next.jar', content)])
        self.path.write_bytes(content)
        results = self.read()
        self.assertEqual(sum(x[0] == 'CANDIDATE' for x in results), 3)
        self.assertEqual(results[-1][0], 'LIMIT')

    def test_global_count_and_size_budget(self):
        self.write([{'file': 'lib.jar'}], [('lib.jar', jar({'id': 'lib'}))])
        for state in [[64, 0], [0, 32 * 1024 * 1024]]:
            self.assertEqual(inspect_nested(self.path, lambda size: None, state)[0][0], 'LIMIT')

    def test_cancellation_and_unsupported_jarjar(self):
        self.write([], [('META-INF/jarjar/metadata.json', b'{}')])
        self.assertEqual(inspect_nested(self.path, lambda size: None, [0, 0], lambda: True), [])
        self.assertEqual(self.read()[0][0], 'UNKNOWN')

    def test_metadata_budget_refusal_is_unknown(self):
        self.write([{'file': 'lib.jar'}])
        def refuse(size):
            raise ValueError('budget')
        self.assertEqual(inspect_nested(self.path, refuse, [0, 0])[0][0], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
