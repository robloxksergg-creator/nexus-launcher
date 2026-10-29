"""Make an isolated source copy with an explicit build-time release identity."""
import argparse
from pathlib import Path
import re
import shutil


def prepare(source, destination, version):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError('Variant destination must be new and outside source')
    if not re.fullmatch(r'[0-9]{1,6}\.[0-9]{1,6}\.[0-9]{1,6}', version):
        raise ValueError('Numeric release version required')
    paths = ['nexus_launcher', 'packaging', 'assets', 'LICENSE', 'COPYRIGHT.md']
    destination.mkdir()
    for name in paths:
        origin = source / name
        if origin.is_dir():
            shutil.copytree(origin, destination / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copyfile(origin, destination / name)
    identity = destination / 'nexus_launcher/public_update_identity.py'
    text, count = re.subn(r'^VERSION = "[0-9.]+"$', f'VERSION = "{version}"',
                          identity.read_text(encoding='utf-8'), flags=re.MULTILINE)
    if count != 1:
        raise ValueError('Unexpected build identity source')
    identity.write_text(text, encoding='utf-8')
    components = ', '.join(version.split('.') + ['0'])
    for filename in ('public_version_info.txt', 'public_bootstrap_version_info.txt'):
        metadata = destination / 'packaging/metadata' / filename
        text = metadata.read_text(encoding='utf-8')
        text = re.sub(r'(filevers|prodvers)=\([0-9, ]+\)', lambda m: m[1] + '=(' + components + ')', text)
        text = re.sub(r"(u'(?:FileVersion|ProductVersion)', u')[0-9.]+(')",
                      lambda m: m[1] + version + m[2], text)
        metadata.write_text(text, encoding='utf-8')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--destination', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    prepare(args.source, args.destination, args.version)
