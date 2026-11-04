"""Prepare hash-pinned coordinated release assets; no private key or live accounts."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shutil
import urllib.request
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SOURCE = '59373a53f7675dcc5d1088b4f6e71769eac5fbd6'
PUBLIC_KEY = 'e5df7b42b312755a66e6f6c88368529172c4e4ed28d37354d4eea1402900925b'
PACKAGES = {
 'installer/NEXUS-Setup.exe': 'a21af9417e37416756f0e6a1576440a95b020bc3019319a46911447b047cb80a',
 'windows/NEXUS-Managed-1.0.7-Windows-x64.zip': '0019bbe54884c501bda595307470a87d12eefc2fe9de87f59b92e31fc17647d4',
 'linux/NEXUS-1.0.7-Linux-x64.tar.gz': '08b0cd78823cb04b192c74d4da1ff03cd702f1b634315f21e26bbdcda7546099',
 'macos/NEXUS-1.0.7-macOS-arm64.zip': '948578c9a0f5bd61dd5d375791caa552c9f5847797f0348f90b5b8f3f1f389f4',
}

def digest(path):
 with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def prepare(root, output, approval, notes, acceptance):
 root, output = Path(root), Path(output)
 if output.exists(): raise ValueError('New release directory required')
 record=json.loads(Path(acceptance).read_text(encoding='utf-8'))
 install_record=json.loads((root/'acceptance/full-install-acceptance.json').read_text(encoding='utf-8'))
 if install_record.get('version')!='1.0.7' or install_record.get('files_verified')!=5539 or install_record.get('completion_visible') is not True or install_record.get('installer_copy_verified') is not True: raise ValueError('Full installation acceptance missing')
 if record.get('source_commit')!=SOURCE: raise ValueError('Acceptance source mismatch')
 if record.get('preinstall_ui_verified') is not True or record.get('user_data_preserved') is not True or [x.get('version') for x in record.get('versions',[])]!=['1.0.6','1.0.7'] or any(x.get('native_readiness')!='PASS' for x in record['versions']): raise ValueError('Native acceptance missing')
 for name, expected in PACKAGES.items():
  if digest(root/name)!=expected: raise ValueError('Package hash mismatch: '+name)
 compact=json.loads(Path(approval).read_text(encoding='utf-8'))
 if compact['source_commit']!=SOURCE or compact['schema']!=2 or compact['key_id']!='nexus-public-preview-20261029': raise ValueError('Wrong approval identity')
 archive=root/'windows/NEXUS-Managed-1.0.7-Windows-x64.zip'
 files=[]
 with zipfile.ZipFile(archive) as z:
  for item in z.infolist():
   with z.open(item) as s: sha=hashlib.file_digest(s,'sha256').hexdigest()
   files.append({'path':item.filename,'size':item.file_size,'sha256':sha})
 payload={**compact['release'],'files':files}
 canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
 if hashlib.sha256(canonical).hexdigest()!=compact['canonical_sha256']: raise ValueError('Signed payload reconstruction mismatch')
 Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(base64.b64decode(compact['signature'],validate=True),canonical)
 if payload['version']!='1.0.7' or payload['sha256']!=digest(archive) or payload['size']!=archive.stat().st_size: raise ValueError('Signed package identity mismatch')
 output.mkdir()
 for name in PACKAGES: shutil.copyfile(root/name,output/Path(name).name)
 envelope={k:compact[k] for k in ['schema','key_id','signature']};envelope['release']=payload
 (output/'portable-envelope.json').write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
 shutil.copyfile(notes,output/'RELEASE-NOTES.md');shutil.copyfile(acceptance,output/'windows-update-acceptance.json')
 shutil.copyfile(root/'acceptance/full-install-acceptance.json',output/'windows-install-acceptance.json')
 (output/'SHA256SUMS.txt').write_text(''.join(digest(x)+'  '+x.name+'\n' for x in sorted(output.iterdir()) if x.is_file()),encoding='utf-8')
 print('Verified three platform packages, new installer, owner signature and native acceptance')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--approval',required=True);p.add_argument('--notes',required=True);p.add_argument('--acceptance',required=True);a=p.parse_args();prepare(a.input,a.output,a.approval,a.notes,a.acceptance)
