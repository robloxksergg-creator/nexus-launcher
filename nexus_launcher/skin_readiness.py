"""Read-only skin component inspection; never downloads or executes a JAR."""
from pathlib import Path
import io
import zipfile

SUPPORTED_LOADERS = {'fabric', 'forge', 'neoforge', 'quilt'}


def skin_component(folder: Path, loader: str) -> str:
    if loader not in SUPPORTED_LOADERS:
        return 'vanilla'
    mods = folder / 'mods'
    if not mods.is_dir() or mods.is_symlink():
        return 'missing'
    # Filename alone is not evidence that the component is actually present.
    for index, jar in enumerate(mods.glob('*.jar')):
        if index >= 512:
            return 'unproven'
        if jar.is_symlink():
            continue
        try:
            if jar.stat().st_size > 128 * 1024 * 1024:
                continue
            with zipfile.ZipFile(jar) as archive:
                names = archive.namelist()
                if len(names) > 16384:
                    continue
                # 15.1 Universal stores the actual loader in a bounded nested JAR.
                nested = 'META-INF/jar-jar/CustomSkinLoader-Common.jar'
                family = 'fabric' if loader == 'quilt' else loader
                if nested in names and any(n.startswith(f'customskinloader/bootstrap/{family}/') and n.endswith('.class') for n in names):
                    info = archive.getinfo(nested)
                    if info.file_size <= 8 * 1024 * 1024:
                        with archive.open(info) as source:
                            raw = source.read(8 * 1024 * 1024 + 1)
                        if len(raw) <= 8 * 1024 * 1024:
                            with zipfile.ZipFile(io.BytesIO(raw)) as common:
                                if len(common.infolist()) <= 16384 and 'customskinloader/CustomSkinLoader.class' in common.namelist():
                                    return 'present'
                if 'customskinloader/CustomSkinLoader.class' not in names:
                    continue
                marker = 'fabric.mod.json' if loader in {'fabric', 'quilt'} else (
                    'META-INF/neoforge.mods.toml' if loader == 'neoforge' else 'META-INF/mods.toml')
                if marker in names or loader == 'neoforge' and 'META-INF/mods.toml' in names:
                    return 'present'
        except (OSError, ValueError, RuntimeError, NotImplementedError, EOFError, zipfile.BadZipFile):
            continue
    return 'missing'
