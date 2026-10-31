"""Reviewed candidate asset selection; no copies, downloads or source deletion."""
from pathlib import Path


RETIRED_ASSETS = frozenset({
    'archvale-world-art.png', 'pinewood-world-art.png',
    'elderfall-world-art.png', 'ironveil-world-art.png',
    'pinewood-fabric-pack.zip', 'elderfall-fabric-pack.zip',
    'nexus-tech-neoforge-pack.zip',
})
RESOURCE_FOLDERS = frozenset({'academy', 'approved-ui', 'studio', 'ui2'})


def asset_datas(root):
    assets = Path(root) / 'assets'
    result = []
    for path in sorted(assets.iterdir()):
        if path.is_symlink():
            raise ValueError('Asset symlinks are not allowed')
        if path.is_file():
            if path.name in RETIRED_ASSETS:
                continue
            if path.suffix.lower() not in {'.png', '.ico', '.icns', '.json', '.svg'}:
                raise ValueError('Unreviewed root asset type: ' + path.name)
            result.append((str(path), 'assets'))
        elif path.name in RESOURCE_FOLDERS:
            for child in sorted(path.rglob('*')):
                if child.is_symlink():
                    raise ValueError('Asset symlinks are not allowed')
                if child.is_file():
                    if child.suffix.lower() not in {'.js', '.css', '.html', '.png', '.svg', '.json'}:
                        raise ValueError('Unreviewed resource type: ' + child.name)
                    relative = child.relative_to(assets)
                    result.append((str(child), 'assets/' + relative.parent.as_posix()))
    return result
