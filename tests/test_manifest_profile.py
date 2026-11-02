import unittest
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from nexus_launcher.build_file_manifest import validate_profile, github_asset_name


class ManifestProfileTests(unittest.TestCase):
    def valid(self, **changes):
        args = dict(pack_id='example', server='play.example.test:25565', minecraft='1.21.1',
                    loader='neoforge', loader_version='21.1.248', repository='Owner/Packs', visibility='public')
        args.update(changes)
        return validate_profile(**args)

    def test_legacy_gearmorph_profile(self):
        self.valid(pack_id='gearmorph', server='playgearmorph.bisquitmc.net',
                   repository='NexusMC202/website_NexusMC', visibility='internal')

    def test_independent_fabric_and_vanilla_profiles(self):
        self.valid(loader='fabric', loader_version='0.16.10')
        self.valid(loader='vanilla', loader_version='', server='[2001:db8::1]:25565')

    def test_invalid_configuration_rejected(self):
        for changes in [{'pack_id': '../other'}, {'server': 'user:secret@example.test'},
                {'server': 'host:0'}, {'server': 'host/path'}, {'server': 'host:65536'},
                {'repository': 'https://github.com/a/b'}, {'repository': '../repo'},
                {'loader': 'quilt'}, {'loader_version': ''}, {'minecraft': 'latest'},
                {'loader': 'vanilla', 'loader_version': '21'}, {'visibility': 'hidden'}]:
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.valid(**changes)

    def test_existing_asset_name_contract(self):
        self.assertEqual(github_asset_name('a--Fresh Buckets 3D UI.zip'), 'a--Fresh.Buckets.3D.UI.zip')

    def test_generator_uses_independent_profile_and_hashes(self):
        # Temporary synthetic config only, no game/runtime or release publication.
        with tempfile.TemporaryDirectory(prefix='nexus-manifest-profile-') as folder:
            root = Path(folder)
            instance = root / 'instance'
            (instance / 'config').mkdir(parents=True)
            content = b'{"synthetic":true}'
            (instance / 'config/example.json').write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            state = root / 'state.json'
            state.write_text(json.dumps({'managed_files': {'config/example.json': digest}}), encoding='utf-8')
            output = root / 'manifest.json'
            result = subprocess.run([sys.executable, '-B', '-m', 'nexus_launcher.build_file_manifest',
                str(instance), str(state), str(output), str(root / 'assets'), '--version', '2.0',
                '--tag', 'sample-2.0', '--pack-id', 'sample', '--server-address', 'play.example.test',
                '--minecraft', '1.20.1', '--loader', 'fabric', '--loader-version', '0.16.10',
                '--repository', 'Example/Packs', '--visibility', 'public'],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual((payload['pack'], payload['minecraft'], payload['loader'],
                              payload['loaderVersion'], payload['minecraft_server']),
                             ('sample', '1.20.1', 'fabric', '0.16.10', 'play.example.test'))
            self.assertEqual(payload['files'][0]['sha256'], digest)
            self.assertTrue(payload['files'][0]['url'].startswith('https://github.com/Example/Packs/releases/download/sample-2.0/'))
            self.assertEqual((instance / 'config/example.json').read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
