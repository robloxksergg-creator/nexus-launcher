"""Signed online provisioning. No process creation, elevation or legacy migration."""
import hashlib
import shutil
import os
from pathlib import Path
from nexus_launcher.bootstrap_installation import provision_initial
from nexus_launcher.portable_package import verify_portable_inventory, verify_staged_portable
from nexus_launcher.portable_transition import _read
from nexus_launcher.resource_limits import ensure_space
from nexus_launcher.safe_paths import checked_path, pinned_directory
from nexus_launcher.signed_release import verify_envelope
from nexus_launcher.user_instances import atomic_json
MARKER='online-install.json'
APPLICATION='NEXUS.exe'

def installer_digest(source):
 with Path(source).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def validate_destination(directory,source):
 directory=Path(directory)
 if not directory.is_absolute() or directory==Path(directory.anchor):raise ValueError('INSTALL_DIRECTORY')
 directory=directory.absolute();checked_path(directory,'probe')
 digest=installer_digest(source)
 if directory.exists():
  if checked_path(directory,MARKER).exists():
   marker=_read(directory,MARKER)
   if marker.get('schema')!=1 or marker.get('application')!='nexus-online' or marker.get('installer_sha256')!=digest:raise ValueError('INSTALL_ALREADY_OWNED')
  elif any(directory.iterdir()):raise ValueError('INSTALL_DIRECTORY_NOT_EMPTY')
  target=checked_path(directory,APPLICATION)
  if target.exists() and installer_digest(target)!=digest:raise ValueError('INSTALL_EXECUTABLE_CONFLICT')
 return directory,digest

def installed_root(executable):
 executable=Path(executable).absolute()
 if executable.name!=APPLICATION or not checked_path(executable.parent,MARKER).exists():return None
 marker=_read(executable.parent,MARKER)
 if marker!={'schema':1,'application':'nexus-online','phase':'COMPLETE','installer_sha256':installer_digest(executable)}:raise ValueError('INSTALL_RECEIPT_INVALID')
 return executable.parent

def install(directory,source,transport,emit,*,keys=None):
 root,digest=validate_destination(directory,source)
 # The Windows entry point holds the installation lifetime lease throughout.
 with pinned_directory(root,create=True):
  marker=checked_path(root,MARKER)
  complete=False
  if marker.exists():complete=_read(root,MARKER).get('phase')=='COMPLETE'
  if not complete:atomic_json(marker,{'schema':1,'application':'nexus-online','phase':'PREPARING','installer_sha256':digest})
  if not checked_path(root,'active.json').exists():
   emit('CHECKING',None,None)
   envelope=transport.manifest();payload=verify_envelope(envelope,keys=keys)
   if payload.get('available') is not True or payload.get('platform')!='windows' or payload.get('arch')!='x64':raise ValueError('INSTALL_PLATFORM')
   inventory=verify_portable_inventory(envelope,keys=keys)
   ensure_space(root,payload['size']+sum(size for _,size,_ in inventory.files))
   # Refuse paths unsupported by the machine rather than weakening path checks.
   if os.name=='nt':
    import winreg
    try:
     with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\FileSystem') as key:long_paths=winreg.QueryValueEx(key,'LongPathsEnabled')[0]==1
    except OSError:long_paths=False
    if not long_paths and any(len(str(root/'slots'/('portable-stage-'+'x'*8)/'files'/name))>=248 for name,_,_ in inventory.files):raise ValueError('INSTALL_PATH_TOO_LONG')
   cache=checked_path(root,'cache')
   with pinned_directory(cache,create=True):
    emit('DOWNLOADING',0,payload['size'])
    archive=Path(transport.download(payload,cache,lambda done,total:emit('DOWNLOADING',done,total))).absolute()
    if archive.parent!=cache or not archive.name.startswith('package-') or archive.suffix!='.zip':raise ValueError('INSTALL_CACHE_PATH')
    emit('VERIFYING',None,None)
    provision_initial(root,archive,envelope,platform='windows',arch='x64',keys=keys)
    # Delete only the exact exclusive cache file returned by this attempt.
    checked_path(cache,archive.name).unlink()
  pointer=_read(root,'active.json')
  if not isinstance(pointer,dict) or set(pointer)!={'slot'} or not isinstance(pointer['slot'],str) or not pointer['slot'].startswith('portable-stage-'):raise ValueError('INSTALL_POINTER')
  verify_staged_portable(checked_path(root,'slots/'+pointer['slot']),keys=keys)
  target=checked_path(root,APPLICATION)
  if not target.exists():
   ensure_space(root,Path(source).stat().st_size)
   # Exclusive creation cannot replace a concurrently introduced file.
   with Path(source).open('rb') as input_stream,target.open('xb') as output:
    shutil.copyfileobj(input_stream,output,1024*1024);output.flush();os.fsync(output.fileno())
  if installer_digest(target)!=digest:raise ValueError('INSTALL_EXECUTABLE_CHANGED')
  atomic_json(marker,{'schema':1,'application':'nexus-online','phase':'COMPLETE','installer_sha256':digest})
  emit('COMPLETE',None,None)
  return target
