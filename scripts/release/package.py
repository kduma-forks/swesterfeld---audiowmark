#!/usr/bin/env python3
"""Stage standalone CLI or full assets with their sources, recipes and required notices."""
import argparse
import json
import pathlib
import shutil
import subprocess
import tarfile
import zipfile
from provenance import revision
from sources import entries

ROOT = pathlib.Path(__file__).resolve().parents[2]
TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
# Programs installed in bin/ for each variant; the full variant also ships its own FFmpeg.
TOOLS = {'cli': ('audiowmark',), 'full': ('audiowmark', 'videowmark', 'ffmpeg', 'ffprobe')}

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

def ffmpeg_info(binary):
    # Executed from the staged copy, so the recorded configuration is the packaged binary's.
    version = subprocess.check_output([str(binary), '-version'], stderr=subprocess.STDOUT, text=True).splitlines()[0]
    buildconf = subprocess.check_output([str(binary), '-buildconf'], stderr=subprocess.STDOUT, text=True).splitlines()
    return version, buildconf

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('target', 'version', 'install', 'licenses', 'output', 'work'):
        parser.add_argument('--' + key, required=True, type=str if key in ('target', 'version') else pathlib.Path)
    parser.add_argument('--variant', choices=sorted(TOOLS), default='cli')
    args = parser.parse_args()
    if args.target not in TARGETS:
        raise ValueError('unknown release target: ' + args.target)
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    windows = args.target.startswith('win7-')
    macos = args.target.startswith('macos-')
    suffix = '.exe' if windows else ''
    stage = args.work / f'audiowmark-{args.version}-{args.variant}-{args.target}'
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
    (stage / 'bin').mkdir()
    for name in TOOLS[args.variant]:
        executable = stage / 'bin' / (name + suffix)
        shutil.copy2(args.install / 'bin' / executable.name, executable)
        if macos:
            subprocess.run(['codesign', '--force', '--sign', '-', str(executable)], check=True)
            subprocess.run(['codesign', '--verify', '--strict', str(executable)], check=True)
        subprocess.run(['python3', str(ROOT / 'scripts/release/audit.py'), '--target', args.target,
                        '--binary', str(executable)], check=True)
    shutil.copy2(ROOT / 'manpages/audiowmark.1', stage / 'audiowmark.1')
    if args.variant == 'full':
        shutil.copy2(ROOT / 'manpages/videowmark.1', stage / 'videowmark.1')
    metadata = dict(version=args.version, target=args.target, kind=args.variant, variant=args.variant,
                    commit=revision(), dependencies=dict(schema=1, sources=entries(args.variant)))
    if args.variant == 'full':
        version, buildconf = ffmpeg_info(stage / 'bin' / ('ffmpeg' + suffix))
        metadata.update(ffmpeg_version=version, ffmpeg_buildconf=buildconf)
    (stage / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    archive(stage, args.output, windows)

if __name__ == '__main__':
    main()
