#!/usr/bin/env python3
"""Stage standalone CLI assets with their sources, recipes and required notices."""
import argparse
import json
import pathlib
import shutil
import subprocess
import tarfile
import zipfile
from provenance import revision

ROOT = pathlib.Path(__file__).resolve().parents[2]

def archive(root, output, windows):
    if windows:
        destination = output / (root.name + '.zip')
        with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    z.write(path, path.relative_to(root.parent))
    else:
        destination = output / (root.name + '.tar.gz')
        with tarfile.open(destination, 'w:gz') as tar:
            tar.add(root, arcname=root.name)
    print(destination)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('target', 'version', 'install', 'licenses', 'output', 'work'):
        parser.add_argument('--' + key, required=True, type=str if key in ('target', 'version') else pathlib.Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    windows = args.target.startswith('win7-')
    macos = args.target.startswith('macos-')
    stage = args.work / f'audiowmark-{args.version}-cli-{args.target}'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    shutil.copytree(args.licenses, stage / 'licenses')
    shutil.copy2(ROOT / 'COPYING', stage / 'licenses' / 'audiowmark-COPYING')
    if not macos:
        shutil.copy2(ROOT / 'scripts/release/licenses/GCC-COPYING.RUNTIME', stage / 'licenses/GCC-COPYING.RUNTIME')
    if args.target.startswith('linux-musl-'):
        shutil.copy2(ROOT / 'scripts/release/licenses/musl-COPYRIGHT', stage / 'licenses/musl-COPYRIGHT')
    if windows:
        for notice in ('mingw-w64-COPYING', 'winpthreads-COPYING'):
            shutil.copy2(ROOT / 'scripts/release/licenses' / notice, stage / 'licenses' / notice)
    shutil.copy2(ROOT / 'README.adoc', stage / 'README.adoc')
    shutil.copytree(ROOT / 'scripts/release', stage / 'build-scripts', ignore=shutil.ignore_patterns('__pycache__'))
    metadata = dict(version=args.version, target=args.target, kind='cli', commit=revision(),
                    dependencies=json.loads((ROOT / 'scripts/release/dependencies.lock.json').read_text()))
    (stage / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    executable = stage / 'bin' / ('audiowmark.exe' if windows else 'audiowmark')
    executable.parent.mkdir()
    shutil.copy2(args.install / 'bin' / executable.name, executable)
    shutil.copy2(ROOT / 'manpages/audiowmark.1', stage / 'audiowmark.1')
    if macos:
        subprocess.run(['codesign', '--force', '--sign', '-', str(executable)], check=True)
        subprocess.run(['codesign', '--verify', '--strict', str(executable)], check=True)
    subprocess.run(['python3', str(ROOT / 'scripts/release/audit.py'), '--target', args.target,
                    '--binary', str(executable)], check=True)
    archive(stage, args.output, windows)

if __name__ == '__main__':
    main()
