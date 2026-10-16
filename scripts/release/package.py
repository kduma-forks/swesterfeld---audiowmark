#!/usr/bin/env python3
"""Stage portable CLI/SDK assets, preserving only required installed files."""
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
    for key in ('target','version','install','licenses','output','work'):
        parser.add_argument('--' + key, required=True, type=str if key in ('target','version') else pathlib.Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    windows = args.target.startswith('win7-')
    macos = args.target.startswith('macos-')
    filename = 'audiowmark.dll' if windows else 'libaudiowmark.dylib' if macos else 'libaudiowmark.so'
    if windows:
        candidates = list(args.install.rglob('*audiowmark*.dll'))
    else:
        candidates = [args.install / 'lib' / filename]
    if len(candidates) != 1 or not candidates[0].exists():
        raise RuntimeError('expected exactly one installed shared library: ' + str(candidates))
    kinds = ['sdk'] if args.target.startswith('linux-gnu-') else ['cli','sdk']
    for kind in kinds:
        stage = args.work / f'audiowmark-{args.version}-{kind}-{args.target}'
        if stage.exists(): shutil.rmtree(stage)
        stage.mkdir()
        shutil.copytree(args.licenses, stage / 'licenses')
        shutil.copy2(ROOT / 'COPYING', stage / 'licenses' / 'audiowmark-COPYING')
        if not macos:
            shutil.copy2(ROOT / 'scripts/release/licenses/GCC-COPYING.RUNTIME', stage / 'licenses/GCC-COPYING.RUNTIME')
        if args.target.startswith('linux-musl-'):
            shutil.copy2(ROOT / 'scripts/release/licenses/musl-COPYRIGHT', stage / 'licenses/musl-COPYRIGHT')
        if windows:
            shutil.copy2(ROOT / 'scripts/release/licenses/mingw-w64-COPYING', stage / 'licenses/mingw-w64-COPYING')
            shutil.copy2(ROOT / 'scripts/release/licenses/winpthreads-COPYING', stage / 'licenses/winpthreads-COPYING')
        shutil.copy2(ROOT / 'README.adoc', stage / 'README.adoc')
        shutil.copytree(ROOT / 'scripts/release', stage / 'build-scripts', ignore=shutil.ignore_patterns('__pycache__'))
        metadata = dict(version=args.version, abi=1, target=args.target, kind=kind,
                        commit=revision(),
                        dependencies=json.loads((ROOT / 'scripts/release/dependencies.lock.json').read_text()))
        (stage / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        if kind == 'cli':
            executable = stage / 'bin' / ('audiowmark.exe' if windows else 'audiowmark')
            executable.parent.mkdir()
            shutil.copy2(args.install / 'bin' / executable.name, executable)
            shutil.copy2(ROOT / 'manpages/audiowmark.1', stage / 'audiowmark.1')
            binaries = [executable]
        else:
            (stage / 'lib').mkdir()
            library = stage / 'lib' / filename
            shutil.copy2(candidates[0], library)
            if not windows and not macos:
                # Consumers linked by -laudiowmark need the ABI SONAME in the SDK.
                (stage / 'lib' / 'libaudiowmark.so.1').symlink_to(filename)
            (stage / 'include').mkdir()
            shutil.copy2(args.install / 'include/audiowmark.h', stage / 'include/audiowmark.h')
            docs = stage / 'docs'; docs.mkdir()
            for source in (ROOT / 'docs').glob('api*'):
                if source.is_file(): shutil.copy2(source, docs / source.name)
            for source in (ROOT / 'docs').glob('bindings*'):
                if source.is_file(): shutil.copy2(source, docs / source.name)
            shutil.copytree(ROOT / 'examples', stage / 'examples', ignore=shutil.ignore_patterns('target','bin','obj','__pycache__'))
            # Import archives are only link metadata, not runtime dependencies.
            for source in (args.install / 'lib').glob('*.dll.a'):
                shutil.copy2(source, stage / 'lib' / source.name)
            binaries = [library]
        if macos:
            for binary in binaries:
                if kind == 'sdk':
                    subprocess.run(['install_name_tool','-id','@rpath/libaudiowmark.dylib',str(binary)],check=True)
                subprocess.run(['codesign','--force','--sign','-',str(binary)],check=True)
                subprocess.run(['codesign','--verify','--strict',str(binary)],check=True)
        for binary in binaries:
            subprocess.run(['python3',str(ROOT/'scripts/release/audit.py'),'--target',args.target,'--binary',str(binary),
                            '--header',str(ROOT/'include/audiowmark.h'),'--kind',kind],check=True)
        archive(stage,args.output,windows)

if __name__ == '__main__':
    main()
