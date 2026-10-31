"""Include Qt's source notices when its Linux wheel omits license files.

The PySide6 umbrella wheel is an alias. Preserve each Qt distribution's actual
METADATA and use the checksum-pinned matching upstream source notice set.
No network, installs, license exemptions or generic missing-license fallback.
"""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import runpy
import tempfile

HERE = Path(__file__).resolve().parent
QT_NAMES = frozenset({'pyside6', 'pyside6-addons', 'pyside6-essentials', 'shiboken6'})
SOURCE_SHA = 'd2c896f7f1a6a7ea4c9f98cfe317272fd139703ddf612b86999f09e48aeef0e6'


def collect(destination, pyside_notices):
    verify = runpy.run_path(str(HERE / 'verify_notices.py'))['verify']
    source = Path(pyside_notices)
    verify(source)
    provenance = json.loads((source / 'inventory.json').read_text(encoding='utf-8'))
    if (provenance.get('archive_sha256') != SOURCE_SHA or
            provenance.get('archive_prefix') != 'pyside-setup-everywhere-src-6.8.3'):
        raise ValueError('Matching pinned PySide6 source notices required')
    distributions = {d.metadata['Name'].lower().replace('_', '-'): d
                     for d in metadata.distributions() if d.metadata['Name']}
    prepared = []
    for name in sorted(QT_NAMES):
        dist = distributions[name]
        if dist.version != '6.8.3':
            raise ValueError('Qt distribution/source version mismatch')
        text = dist.read_text('METADATA')
        if not text:
            raise ValueError('Qt distribution metadata missing')
        prepared.append((name, text.encode('utf-8')))
    with tempfile.TemporaryDirectory(prefix='nexus-linux-notices-') as temporary:
        root = Path(temporary)
        python = root / 'python'
        runpy.run_path(str(HERE / 'collect_python_notices.py'))['collect'](
            sorted(set(distributions) - QT_NAMES), python)
        qt = root / 'qt-metadata'
        qt.mkdir()
        files = []
        for name, content in prepared:
            path = name + '-METADATA.txt'
            (qt / path).write_bytes(content)
            files.append({'path': path, 'sha256': hashlib.sha256(content).hexdigest()})
        (qt / 'inventory.json').write_text(json.dumps({
            'schema': 1, 'kind': 'notice-bundle', 'license_clearance': 'NOT ESTABLISHED',
            'scope': 'Qt distribution metadata; actual notices in matching pyside-source group',
            'files': files}), encoding='utf-8')
        return runpy.run_path(str(HERE / 'assemble_notice_bundle.py'))['assemble'](
            [('python', python), ('qt-distribution-metadata', qt), ('pyside-source', source)], destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--pyside-notices', required=True)
    args = parser.parse_args()
    collect(args.output, args.pyside_notices)
