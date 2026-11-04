"""Allowlisted NeonPhantom XR source and portable archives, without user data."""
import argparse
import hashlib
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parent
PREFIX = 'NeonPhantom-XR'
FILES = '''README.md LICENSE .gitignore .gitattributes VERSION SECURITY.md SECURITY-REVIEW.md
RELEASING.md VALIDATION.md THIRD-PARTY-NOTICES.txt BUNDLE-README.md WINDOWS-README.md
QUEST-README.md MODEL-UPGRADE.md API.md video_pipeline.py vr180_pipeline.py
cutout_engines.py model_manager.py model_runtime.py media_security.py secure_download.py windows_overlay.py
start.sh bar-dancer.sh gpu-python.sh setup-windows.cmd setup-windows.ps1
start-windows.cmd start-windows.ps1 setup-quest.sh setup-quest-gpu.sh setup-quest-gpu.cmd
start-quest.sh start-quest.cmd requirements-ai.txt requirements-ai.lock.txt
requirements-gpu.txt requirements-gpu.lock.txt requirements-quest.txt requirements-quest-gpu.txt
requirements-windows.txt package_release.py deskdanced/Cargo.toml deskdanced/Cargo.lock
frontend/package.json frontend/package-lock.json frontend/index.html frontend/vite.config.js
frontend/vendor/deepmerge-safe/package.json frontend/vendor/deepmerge-safe/index.cjs
frontend/vendor/deepmerge-safe/LICENSE frontend/vendor/deepmerge-safe/README.md
quest/app/package.json quest/app/package-lock.json quest/app/index.html samples/.gitkeep
'''.split()
TREES = {'deskdanced/src':{'.rs'}, 'frontend/src':{'.js','.css','.svelte'},
         'quest/app/src':{'.js','.css'}, 'tests':{'.py','.mjs'},
         'scripts':{'.py','.mjs'}, '.github':{'.yml'}}
SCREENSHOTS = ['studio.png', 'quest-viewer.png', 'studio-mobile.png']


def source_paths():
    paths = [ROOT / name for name in FILES]
    paths += sorted((ROOT/'quest').glob('*.py'))
    for folder, suffixes in TREES.items():
        paths += [p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts]
    paths += [ROOT/'docs/screenshots'/name for name in SCREENSHOTS]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing file or symlink in source allowlist: {path.relative_to(ROOT)}')
    return sorted(set(paths))


def write_archive(path, paths):
    from scripts.release_audit import check_content
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for relative, source in sorted(paths):
            if source.is_symlink():
                raise ValueError(f'Symlink rejected: {relative}')
            data = source.read_bytes()
            check_content(relative, data)
            entry = zipfile.ZipInfo(PREFIX+'/'+relative, date_time=(2026,11,4,0,0,0))
            entry.create_system = 3
            mode = 0o755 if relative.endswith('.sh') or relative.endswith('/deskdanced') else 0o644
            entry.external_attr = (stat.S_IFREG | mode) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    from scripts.release_audit import check_archive
    check_archive(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix(path.suffix+'.sha256').write_text(f'{digest}  {path.name}\n')
    print(f'{path.name}: {digest}')


def package(platform, destination):
    paths = [(p.relative_to(ROOT).as_posix(), p) for p in source_paths()]
    if platform != 'Source':
        for folder in ('frontend/build', 'quest/site'):
            if not (ROOT/folder/'index.html').is_file():
                raise ValueError(f'Build {folder} before packaging')
            paths += [(p.relative_to(ROOT).as_posix(),p) for p in (ROOT/folder).rglob('*') if p.is_file()]
        suffix = '.exe' if platform == 'Windows' else ''
        binary = ROOT/f'deskdanced/target/release/deskdanced{suffix}'
        cross = ROOT/'deskdanced/target/x86_64-pc-windows-gnu/release/deskdanced.exe'
        if platform == 'Windows' and cross.is_file():
            binary = cross
        if not binary.is_file():
            raise ValueError(f'Build {platform} binary before packaging')
        paths.append((f'deskdanced/target/release/deskdanced{suffix}',binary))
    destination = Path(destination); destination.mkdir(parents=True,exist_ok=True)
    name = f'{PREFIX}-Source.zip' if platform == 'Source' else f'{PREFIX}-{platform}-x64.zip'
    write_archive(destination/name,paths)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--platform',choices=['source','Linux','Windows','both','all'],default='all')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    args=parser.parse_args()
    platforms = {'source':['Source'],'both':['Linux','Windows'],'all':['Source','Linux','Windows']}.get(args.platform,[args.platform])
    for platform in platforms:
        package(platform,args.output)
