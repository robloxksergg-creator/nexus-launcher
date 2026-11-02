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

SOURCE = 'd5dd5404462a071a743ea55a2e4873e7c668fc53'
PUBLIC_KEY = 'e5df7b42b312755a66e6f6c88368529172c4e4ed28d37354d4eea1402900925b'
PACKAGES = {
 'windows/NEXUS-Managed-1.0.5-Windows-x64.zip': 'dde4e63f4f71319fb1b1c49dade68683a5f350030b6447c6bd090c34570e6de2',
 'linux/NEXUS-1.0.5-Linux-x64.tar.gz': 'ac9590f756fa72600d4a1bd0a5e95b004b7dc0e2b8742340e4aa690409e33731',
 'macos/NEXUS-1.0.5-macOS-arm64.zip': '5444a4f6b415f97bb4ff11067925c9c3483037dce14883f166d605347e2e965f',
}

def digest(path):
 with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def prepare(root, output, approval, notes, acceptance):
 root, output = Path(root), Path(output)
 if output.exists(): raise ValueError('New release directory required')
 record=json.loads(Path(acceptance).read_text(encoding='utf-8'))
 if record.get('preinstall_ui_verified') is not True or record.get('user_data_preserved') is not True or [x.get('version') for x in record.get('versions',[])]!=['1.0.4','1.0.5'] or any(x.get('native_readiness')!='PASS' for x in record['versions']): raise ValueError('Native acceptance missing')
 for name, expected in PACKAGES.items():
  if digest(root/name)!=expected: raise ValueError('Package hash mismatch: '+name)
 compact=json.loads(Path(approval).read_text(encoding='utf-8'))
 if compact['source_commit']!=SOURCE or compact['schema']!=2 or compact['key_id']!='nexus-public-preview-20261029': raise ValueError('Wrong approval identity')
 archive=root/'windows/NEXUS-Managed-1.0.5-Windows-x64.zip'
 files=[]
 with zipfile.ZipFile(archive) as z:
  for item in z.infolist():
   with z.open(item) as s: sha=hashlib.file_digest(s,'sha256').hexdigest()
   files.append({'path':item.filename,'size':item.file_size,'sha256':sha})
 payload={**compact['release'],'files':files}
 canonical=json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
 if hashlib.sha256(canonical).hexdigest()!=compact['canonical_sha256']: raise ValueError('Signed payload reconstruction mismatch')
 Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY)).verify(base64.b64decode(compact['signature'],validate=True),canonical)
 if payload['version']!='1.0.5' or payload['sha256']!=digest(archive) or payload['size']!=archive.stat().st_size: raise ValueError('Signed package identity mismatch')
 output.mkdir()
 for name in PACKAGES: shutil.copyfile(root/name,output/Path(name).name)
 envelope={k:compact[k] for k in ['schema','key_id','signature']};envelope['release']=payload
 (output/'portable-envelope.json').write_text(json.dumps(envelope,ensure_ascii=False,indent=2),encoding='utf-8')
 installer=output/'NEXUS-Setup.exe'
 url='https://github.com/robloxksergg-creator/nexus-launcher/releases/download/installer-v1.0.0-preview.2/NEXUS-Setup.exe'
 with urllib.request.urlopen(url,timeout=90) as s,installer.open('xb') as d: shutil.copyfileobj(s,d)
 if digest(installer)!='32be7d7243326e92e5be79fbc88acf045705caffc4f72a96ba33a172e4844d2d': raise ValueError('Installer hash mismatch')
 shutil.copyfile(notes,output/'RELEASE-NOTES.md');shutil.copyfile(acceptance,output/'windows-update-acceptance.json')
 (output/'SHA256SUMS.txt').write_text(''.join(digest(x)+'  '+x.name+'\n' for x in sorted(output.iterdir()) if x.is_file()),encoding='utf-8')
 print('Verified three platform packages, existing installer, owner signature and native acceptance')

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--input',required=True);p.add_argument('--output',required=True);p.add_argument('--approval',required=True);p.add_argument('--notes',required=True);p.add_argument('--acceptance',required=True);a=p.parse_args();prepare(a.input,a.output,a.approval,a.notes,a.acceptance)
