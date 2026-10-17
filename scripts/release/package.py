#!/usr/bin/env python3
"""Stage release archives with their sources, recipes and required notices.

--variant cli   emits cli (CLI targets) and sdk (all seven targets; GNU targets are SDK-only).
--variant full  emits full (CLI targets only): audiowmark, videowmark, ffmpeg and ffprobe, and no SDK.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile
import zipfile
from provenance import revision
from sources import entries

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLI_TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
SDK_TARGETS = CLI_TARGETS + ('linux-gnu-x86_64', 'linux-gnu-aarch64')
TOOLS = {'cli': ('audiowmark',), 'full': ('audiowmark', 'videowmark', 'ffmpeg', 'ffprobe')}

def kinds_for(variant, target):
    if variant == 'full':
        if target not in CLI_TARGETS:
            raise ValueError('full packages are not built for ' + target)
        return ['full']
    return ['sdk'] if target.startswith('linux-gnu-') else ['cli', 'sdk']

def library_name(target):
    return 'audiowmark.dll' if target.startswith('win7-') else 'libaudiowmark.dylib' if target.startswith('macos-') else 'libaudiowmark.so'

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

def dependencies(variant):
    return dict(schema=1, sources=entries(variant))

def stage_package(kind, args, windows, macos, stage):
    suffix = '.exe' if windows else ''
    header = ROOT / 'include/audiowmark.h'
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
    if kind == 'sdk':
        metadata = dict(version=args.version, abi=1, target=args.target, kind='sdk', variant='cli',
                        commit=revision(), dependencies=dependencies('cli'))
    else:
        metadata = dict(version=args.version, target=args.target, kind=kind, variant=kind,
                        commit=revision(), dependencies=dependencies(kind))
    binaries = []
    if kind == 'sdk':
        filename = library_name(args.target)
        if windows:
            candidates = list(args.install.rglob('*audiowmark*.dll'))
        else:
            candidates = [args.install / 'lib' / filename]
        if len(candidates) != 1 or not candidates[0].exists():
            raise RuntimeError('expected exactly one installed shared library: ' + str(candidates))
        (stage / 'lib').mkdir()
        library = stage / 'lib' / filename
        shutil.copy2(candidates[0], library)
        if not windows and not macos:
            # Consumers linked by -laudiowmark need the ABI SONAME in the SDK.
            (stage / 'lib' / 'libaudiowmark.so.1').symlink_to(filename)
        (stage / 'include').mkdir()
        shutil.copy2(args.install / 'include/audiowmark.h', stage / 'include/audiowmark.h')
        docs = stage / 'docs'
        docs.mkdir()
        for source in (ROOT / 'docs').glob('api*'):
            if source.is_file():
                shutil.copy2(source, docs / source.name)
        for source in (ROOT / 'docs').glob('bindings*'):
            if source.is_file():
                shutil.copy2(source, docs / source.name)
        shutil.copytree(ROOT / 'examples', stage / 'examples', ignore=shutil.ignore_patterns('target', 'bin', 'obj', '__pycache__'))
        # Import archives are only link metadata, not runtime dependencies.
        for source in (args.install / 'lib').glob('*.dll.a'):
            shutil.copy2(source, stage / 'lib' / source.name)
        binaries.append(library)
        audit_kind = 'sdk'
    else:
        (stage / 'bin').mkdir()
        for name in TOOLS[kind]:
            executable = stage / 'bin' / (name + suffix)
            shutil.copy2(args.install / 'bin' / executable.name, executable)
            binaries.append(executable)
        shutil.copy2(ROOT / 'manpages/audiowmark.1', stage / 'audiowmark.1')
        if kind == 'full':
            shutil.copy2(ROOT / 'manpages/videowmark.1', stage / 'videowmark.1')
        # cli: the audiowmark CLI; full: the four-tool bundle, held to the stricter fully-static rules in audit.py.
        audit_kind = kind
    if kind == 'full':
        version, buildconf = ffmpeg_info(stage / 'bin' / ('ffmpeg' + suffix))
        metadata.update(ffmpeg_version=version, ffmpeg_buildconf=buildconf)
    (stage / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if macos:
        for binary in binaries:
            if kind == 'sdk':
                subprocess.run(['install_name_tool', '-id', '@rpath/libaudiowmark.dylib', str(binary)], check=True)
            subprocess.run(['codesign', '--force', '--sign', '-', str(binary)], check=True)
            subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
    for binary in binaries:
        subprocess.run([sys.executable, str(ROOT / 'scripts/release/audit.py'), '--target', args.target,
                        '--binary', str(binary), '--header', str(header), '--kind', audit_kind], check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for key in ('target', 'version', 'install', 'licenses', 'output', 'work'):
        parser.add_argument('--' + key, required=True, type=str if key in ('target', 'version') else pathlib.Path)
    parser.add_argument('--variant', choices=sorted(TOOLS), default='cli')
    args = parser.parse_args()
    if args.target not in SDK_TARGETS:
        raise ValueError('unknown release target: ' + args.target)
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    windows = args.target.startswith('win7-')
    macos = args.target.startswith('macos-')
    for kind in kinds_for(args.variant, args.target):
        stage = args.work / f'audiowmark-{args.version}-{kind}-{args.target}'
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir()
        stage_package(kind, args, windows, macos, stage)
        archive(stage, args.output, windows)

if __name__ == '__main__':
    main()
