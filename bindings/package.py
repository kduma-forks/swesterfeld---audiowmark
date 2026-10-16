#!/usr/bin/env python3
"""Build GitHub Release attachments from seven extracted native SDKs. No publication."""
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = {
    'win-x64': ('win7-x86_64', 'audiowmark.dll'),
    'linux-x64': ('linux-gnu-x86_64', 'libaudiowmark.so'),
    'linux-arm64': ('linux-gnu-aarch64', 'libaudiowmark.so'),
    'linux-musl-x64': ('linux-musl-x86_64', 'libaudiowmark.so'),
    'linux-musl-arm64': ('linux-musl-aarch64', 'libaudiowmark.so'),
    'osx-x64': ('macos-x86_64', 'libaudiowmark.dylib'),
    'osx-arm64': ('macos-aarch64', 'libaudiowmark.dylib'),
}
SEMVER = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')

def version(value):
    value = value[1:] if value.startswith('v') else value
    match = SEMVER.fullmatch(value)
    if not match or (match[4] and any(p.isdigit() and len(p) > 1 and p[0] == '0' for p in match[4].split('.'))):
        raise ValueError('version must be SemVer with optional v prefix: ' + value)
    return value

def native_library(native_dir, rid):
    target, filename = TARGETS[rid]
    paths = [native_dir / target / 'lib' / filename, native_dir / rid / 'native' / filename, native_dir / rid / filename]
    for path in paths:
        if path.is_file() and path.stat().st_size:
            return path
    raise FileNotFoundError('missing native library for {}: {}'.format(rid, paths[0]))

def native_licenses(native_dir, rid):
    target, _ = TARGETS[rid]
    for directory in (native_dir / target / 'licenses', native_dir / rid / 'licenses'):
        if directory.is_dir() and any(p.is_file() for p in directory.rglob('*')):
            return directory
    raise FileNotFoundError('missing SDK license notices for ' + rid)

def configure_output():
    # Redirected Windows streams otherwise use the ANSI code page. Keep command
    # logs and tracebacks in UTF-8 without altering Unicode subprocess arguments.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')

def run(args, **kwargs):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)

def build_crate(semver, output, work):
    stage = work / 'rust'
    shutil.copytree(ROOT / 'bindings/rust', stage, ignore=shutil.ignore_patterns('target', 'Cargo.lock'))
    manifest = stage / 'Cargo.toml'
    manifest.write_text(re.sub(r'(?m)^version = "[^"]+"', 'version = "' + semver + '"', manifest.read_text()), encoding='utf-8')
    # MSRV is validated in package-consumption jobs; no native build/download exists.
    run(['cargo', 'package', '--manifest-path', manifest, '--allow-dirty', '--no-verify'])
    result = output / ('audiowmark-' + semver + '.crate')
    shutil.copy2(stage / 'target/package' / result.name, result)
    return result

def build_nuget(nuget_version, native_dir, output, work):
    stage = work / 'dotnet'
    shutil.copytree(ROOT / 'bindings/dotnet/Audiowmark', stage, ignore=shutil.ignore_patterns('bin', 'obj'))
    assets = work / 'native-assets'
    originals = {}
    licenses = work / 'native-licenses'
    notices = {}
    for rid, (_, filename) in TARGETS.items():
        original = native_library(native_dir, rid)
        destination = assets / rid / 'native' / filename
        destination.parent.mkdir(parents=True)
        shutil.copy2(original, destination)
        originals['runtimes/' + rid + '/native/' + filename] = original
        license_dir = native_licenses(native_dir, rid)
        for notice in sorted(license_dir.rglob('*')):
            if not notice.is_file():
                continue
            relative = notice.relative_to(license_dir)
            destination = licenses / rid / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(notice, destination)
            notices['licenses/' + rid + '/' + relative.as_posix()] = notice
    run(['dotnet', 'pack', stage / 'Audiowmark.csproj', '--configuration', 'Release',
         '--output', output, '-p:Version=' + nuget_version, '-p:PackageVersion=' + nuget_version,
         '-p:NativeAssetsDir=' + str(assets), '-p:NativeLicensesDir=' + str(licenses)])
    result = output / ('Audiowmark.' + nuget_version + '.nupkg')
    with zipfile.ZipFile(result) as archive:
        natives = {name for name in archive.namelist() if name.startswith('runtimes/')}
        if natives != set(originals):
            raise ValueError('wrong NuGet runtime asset paths: ' + str(sorted(natives)))
        for name, original in originals.items():
            if hashlib.sha256(archive.read(name)).digest() != hashlib.sha256(original.read_bytes()).digest():
                raise ValueError('native asset content changed: ' + name)
        for name, original in notices.items():
            if name not in archive.namelist() or archive.read(name) != original.read_bytes():
                raise ValueError('NuGet package missing or changed SDK notice: ' + name)
        for name in ['lib/netstandard2.0/Audiowmark.Managed.dll', 'build/Audiowmark.targets', 'buildTransitive/Audiowmark.targets', 'README.md', 'LICENSE']:
            if name not in archive.namelist():
                raise ValueError('NuGet package missing: ' + name)
    return result

def main():
    configure_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--nuget-version')
    parser.add_argument('--native-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    semver = version(args.version)
    nuget_version = version(args.nuget_version or semver.split('+')[0])
    if nuget_version != semver.split('+')[0]:
        raise ValueError('NuGet version must equal release SemVer without build metadata')
    native_dir = args.native_dir.resolve()
    # Fail before building either artifact when any required RID is missing.
    for rid in TARGETS:
        native_library(native_dir, rid)
        native_licenses(native_dir, rid)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='audiowmark-pack-') as temporary:
        work = Path(temporary)
        print(build_crate(semver, output, work))
        print(build_nuget(nuget_version, native_dir, output, work))

if __name__ == '__main__':
    main()
