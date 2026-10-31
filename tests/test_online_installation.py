"""Offline signed fixtures only: never execute the synthetic EXE or use HTTP."""
import base64,hashlib,io,json,tempfile,unittest,zipfile
from datetime import UTC,datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from nexus_launcher.online_installation import install,installed_root,validate_destination
from nexus_launcher.signed_release import canonical,METADATA

class Transport:
 def __init__(self):
  self.downloads=0;self.key=Ed25519PrivateKey.generate();self.keys={'fixture':self.key.public_key().public_bytes_raw().hex()}
  files={'launcher.exe':b'SYNTHETIC NOT EXECUTABLE','_internal/runtime.dll':b'SYNTHETIC NOT A DLL'}
  archive=io.BytesIO()
  with zipfile.ZipFile(archive,'w') as z:
   for name,data in files.items():z.writestr(name,data)
  self.data=archive.getvalue();now=datetime.now(UTC)
  self.payload={'format':'nexus-portable-zip-v1','version':'99.0.0','entrypoint':'launcher.exe','channel':METADATA['channel'],'available':True,'platform':'windows','arch':'x64','url':'https://github.com/robloxksergg-creator/nexus-launcher/releases/download/fixture/package.zip','size':len(self.data),'sha256':hashlib.sha256(self.data).hexdigest(),'published_at':(now-timedelta(minutes=1)).isoformat(),'expires_at':(now+timedelta(hours=1)).isoformat(),'files':[{'path':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in files.items()]}
 def manifest(self):return {'schema':2,'key_id':'fixture','release':self.payload,'signature':base64.b64encode(self.key.sign(canonical(self.payload))).decode()}
 def download(self,payload,cache,progress):
  self.downloads+=1;file=cache/'package-fixture.zip';file.write_bytes(self.data);progress(len(self.data),len(self.data));return file

class OnlineInstallationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='nexus-online-test-');self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name);self.source=self.base/'setup.exe';self.source.write_bytes(b'SYNTHETIC INSTALLER');self.root=self.base/'installation';self.transport=Transport();self.events=[]
 def run_install(self):return install(self.root,self.source,self.transport,lambda *args:self.events.append(args),keys=self.transport.keys)
 def test_installs_full_signed_slot_and_copies_only_own_installer(self):
  target=self.run_install();self.assertEqual(target.read_bytes(),self.source.read_bytes());self.assertEqual(installed_root(target),self.root);self.assertEqual(self.transport.downloads,1);self.assertEqual(self.events[-1][0],'COMPLETE');self.assertFalse(any((self.root/'cache').iterdir()));slot=json.loads((self.root/'active.json').read_text())['slot'];self.assertTrue((self.root/'slots'/slot/'files/_internal/runtime.dll').is_file())
 def test_retry_does_not_download_or_replace_installed_package(self):
  self.run_install();before=(self.root/'active.json').read_bytes();self.run_install();self.assertEqual(self.transport.downloads,1);self.assertEqual((self.root/'active.json').read_bytes(),before)
 def test_unrelated_directory_is_preserved(self):
  self.root.mkdir();f=self.root/'user-world.dat';f.write_bytes(b'PRESERVE')
  with self.assertRaises(ValueError):self.run_install()
  self.assertEqual(f.read_bytes(),b'PRESERVE');self.assertEqual(self.transport.downloads,0)
 def test_untrusted_signature_never_downloads(self):
  self.transport.keys={}
  with self.assertRaises(ValueError):self.run_install()
  self.assertEqual(self.transport.downloads,0);self.assertFalse((self.root/'active.json').exists());self.assertFalse((self.root/'NEXUS.exe').exists())
 def test_modified_archive_cannot_become_ready(self):
  self.transport.data=b'corrupt archive'
  with self.assertRaises(Exception):self.run_install()
  self.assertFalse((self.root/'active.json').exists());self.assertFalse((self.root/'NEXUS.exe').exists());self.assertNotIn('COMPLETE',[e[0] for e in self.events])
 def test_wrong_platform_stops_before_download(self):
  self.transport.payload['platform']='macos'
  with self.assertRaises(ValueError):self.run_install()
  self.assertEqual(self.transport.downloads,0)
 def test_disk_failure_stops_before_download(self):
  with patch('nexus_launcher.online_installation.ensure_space',side_effect=OSError('synthetic low space')):
   with self.assertRaises(OSError):self.run_install()
  self.assertEqual(self.transport.downloads,0)
 def test_unknown_receipt_and_replaced_installer_are_rejected(self):
  target=self.run_install();target.write_bytes(b'foreign')
  with self.assertRaises(ValueError):installed_root(target)
  with self.assertRaises(ValueError):self.run_install()
 def test_volume_root_and_relative_path_are_rejected(self):
  for root in [Path('relative-installation'),Path(self.root.anchor)]:
   with self.assertRaises(ValueError):validate_destination(root,self.source)

if __name__=='__main__':unittest.main()
