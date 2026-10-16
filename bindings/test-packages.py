#!/usr/bin/env python3
"""Run C/Rust/C# consumers of actual extracted SDK, .crate and .nupkg artifacts."""
import argparse
import json
import ntpath
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import wave
import xml.etree.ElementTree as ET
from pathlib import Path
from package import TARGETS, configure_output, run, version

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = '0123456789abcdef0123456789abcdef'

def compiler_command(value, windows=None):
    """Windows CC is an executable path; Unix CC may include shell-quoted flags."""
    value = value.strip()
    if not value:
        return []
    if windows is None:
        windows = os.name == 'nt'
    if windows:
        # Preserve Join-Path's backslashes and spaces. subprocess quotes this
        # single argument for CreateProcess; POSIX shlex would eat backslashes.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        return [value]
    return shlex.split(value)

def compiler_environment(compiler, windows=None):
    if windows is None:
        windows = os.name == 'nt'
    if not windows:
        return None
    # GCC's cc1.exe is under lib/gcc, while its imported DLLs live in bin.
    # Scope this PATH to compilation; SDK/CLI/language consumers keep the
    # original stripped environment to expose accidental MSYS dependencies.
    executable = shutil.which(compiler[0]) or compiler[0]
    compiler_dir = ntpath.dirname(ntpath.abspath(executable))
    env = os.environ.copy()
    env['PATH'] = compiler_dir + ';' + env.get('PATH', '')
    return env

def extract_crate(crate, destination):
    with tarfile.open(crate, 'r:gz') as archive:
        members = archive.getmembers()
        roots = {Path(member.name).parts[0] for member in members}
        if len(roots) != 1:
            raise ValueError('crate must have one top-level directory')
        for member in members:
            path = destination / member.name
            if not (member.isfile() or member.isdir()) or not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError('unsafe crate archive entry: ' + member.name)
        archive.extractall(destination)
    return destination / roots.pop()

def make_wav(path):
    # Deterministic, non-silent float-like noise encoded as PCM16, no external tools.
    state = 123456789
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
        block = bytearray()
        for _ in range(44100 * 40):
            state ^= (state << 13) & 0xffffffff
            state ^= state >> 17
            state ^= (state << 5) & 0xffffffff
            state &= 0xffffffff
            block.extend(struct.pack('<h', int((state / 0xffffffff * .5 - .25) * 32767)))
            if len(block) >= 65536:
                output.writeframesraw(block); block.clear()
        output.writeframesraw(block)

def main():
    configure_output()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--crate', type=Path, required=True)
    parser.add_argument('--nuget-feed', type=Path, required=True)
    parser.add_argument('--version', required=True, help='NuGet package version')
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--rid', choices=TARGETS, required=True)
    parser.add_argument('--work-dir', type=Path, required=True)
    parser.add_argument('--framework', default='net8.0')
    parser.add_argument('--cli', type=Path)
    parser.add_argument('--rust-toolchain', default='1.77.2')
    parser.add_argument('--skip-dotnet', action='store_true', help='Only when .NET runtime is unavailable on the native test host')
    args = parser.parse_args()
    nuget_version = version(args.version)
    sdk = args.sdk.resolve(); work = args.work_dir.resolve(); feed = args.nuget_feed.resolve()
    library = sdk / 'lib' / TARGETS[args.rid][1]
    if not library.is_file() or not (sdk / 'include/audiowmark.h').is_file():
        raise FileNotFoundError('SDK missing header or native library: ' + str(sdk))
    if work.exists() and any(work.iterdir()):
        raise ValueError('consumer work directory must be empty: ' + str(work))
    work.mkdir(parents=True, exist_ok=True)
    input_file = work / 'input.wav'; make_wav(input_file)
    unicode_input = work / 'input-żółw.wav'; shutil.copy2(input_file, unicode_input)
    # C: compile against extracted SDK header, resolve the explicit extracted library.
    compiler = compiler_command(os.environ.get('CC', ''))
    if not compiler:
        compiler = [next((c for c in ('cc', 'clang', 'gcc') if shutil.which(c)), 'cc')]
    executable = work / ('c-consumer.exe' if os.name == 'nt' else 'c-consumer')
    command = compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(sdk / 'include'), str(ROOT / 'examples/c/consumer.c'), '-o', str(executable)]
    if sys.platform.startswith('linux'):
        command += ['-ldl']
    run(command, env=compiler_environment(compiler))
    run([executable, library, input_file, work / 'c-marked.wav'])
    # Rust: consume extracted .crate via a path dependency, never a repo project reference.
    vendor = work / 'vendor'; vendor.mkdir()
    crate = extract_crate(args.crate.resolve(), vendor)
    rust = work / 'rust-consumer'
    shutil.copytree(ROOT / 'examples/rust', rust, ignore=shutil.ignore_patterns('target', 'Cargo.lock'))
    manifest = rust / 'Cargo.toml'
    text = manifest.read_text().replace('path = "../../bindings/rust"', 'path = ' + json.dumps(crate.as_posix()))
    manifest.write_text(text, encoding='utf-8')
    rust_env = os.environ.copy()
    if args.rid.startswith('linux-musl-'):
        rust_env['RUSTFLAGS'] = rust_env.get('RUSTFLAGS', '') + ' -Ctarget-feature=-crt-static'
    run(['cargo', '+' + args.rust_toolchain, 'test', '--manifest-path', crate / 'Cargo.toml'], env=rust_env)
    run(['cargo', '+' + args.rust_toolchain, 'run', '--release', '--manifest-path', manifest,
         '--', library, unicode_input, work / 'rust-marked-żółw.wav', work], env=rust_env)
    # C#: the PackageReference restores from the local feed and has its own cache.
    if not args.skip_dotnet:
        dotnet = work / 'dotnet-consumer'
        shutil.copytree(ROOT / 'examples/dotnet', dotnet, ignore=shutil.ignore_patterns('bin', 'obj'))
        config = ET.Element('configuration'); sources = ET.SubElement(config, 'packageSources')
        ET.SubElement(sources, 'clear')
        ET.SubElement(sources, 'add', key='release', value=str(feed))
        ET.SubElement(sources, 'add', key='nuget.org', value='https://api.nuget.org/v3/index.json')
        # Only framework reference packages may come from nuget.org.
        mapping = ET.SubElement(config, 'packageSourceMapping')
        release = ET.SubElement(mapping, 'packageSource', key='release'); ET.SubElement(release, 'package', pattern='Audiowmark')
        public = ET.SubElement(mapping, 'packageSource', key='nuget.org'); ET.SubElement(public, 'package', pattern='Microsoft.*'); ET.SubElement(public, 'package', pattern='NETStandard.Library')
        config_file = dotnet / 'NuGet.Config'; ET.ElementTree(config).write(config_file, encoding='utf-8', xml_declaration=True)
        env = os.environ.copy(); env['NUGET_PACKAGES'] = str(work / 'nuget-cache')
        project = dotnet / 'Consumer.csproj'
        env.pop('LD_LIBRARY_PATH', None)
        env.pop('DYLD_LIBRARY_PATH', None)
        env.pop('DYLD_FALLBACK_LIBRARY_PATH', None)
        frameworks = [args.framework]
        if os.name == 'nt' and args.rid == 'win-x64' and args.framework != 'net48':
            frameworks.append('net48')
        for framework in frameworks:
            if framework == 'net48' and (os.name != 'nt' or args.rid != 'win-x64'):
                raise ValueError('net48 consumers must execute on Windows x64')
            props = ['-p:AudiowmarkVersion=' + nuget_version, '-p:ConsumerFramework=' + framework]
            if framework == 'net48':
                props += ['-p:PlatformTarget=x64', '-p:RuntimeIdentifier=']
                assembly = dotnet / 'bin/Release/net48/Consumer.exe'
                launch = [assembly]
            else:
                props += ['-p:RuntimeIdentifier=' + args.rid]
                assembly = dotnet / 'bin/Release' / framework / args.rid / 'Consumer.dll'
                launch = ['dotnet', assembly]
            run(['dotnet', 'restore', project, '--configfile', config_file] + props, env=env)
            run(['dotnet', 'build', project, '--configuration', 'Release', '--no-restore'] + props, env=env)
            # Require the NuGet-selected native asset, then exercise P/Invoke
            # resolution from an unrelated cwd with no loader overrides.
            packaged_library = assembly.parent / TARGETS[args.rid][1]
            if not packaged_library.is_file():
                raise FileNotFoundError('NuGet failed to copy native asset: ' + str(packaged_library))
            run(launch + [unicode_input, work / ('csharp-' + framework + '-marked-żółw.wav'), work], env=env, cwd=work)
    if args.cli:
        cli = args.cli.resolve()
        cli_marked = work / 'cli-marked.wav'
        run([cli, 'add', input_file, cli_marked, PAYLOAD])
        # Rust/C# default-key outputs are independently decoded by the release CLI.
        for name in ('rust-default.wav',) + (() if args.skip_dotnet else ('csharp-default.wav',)):
            run([cli, 'cmp', work / name, PAYLOAD])
        # Native CLI -> library cross compatibility: tiny extracted-crate consumer.
        source = rust / 'src/main.rs'
        source.write_text('use audiowmark::{Library,Payload};\nfn main() { let args:Vec<_>=std::env::args().collect(); let mut c=Library::load(&args[1]).unwrap().context().unwrap(); assert!(c.detect_file(&args[2]).unwrap().iter().any(|d|d.payload==Payload::from_hex("' + PAYLOAD + '").unwrap())); }\n', encoding='utf-8')
        run(['cargo', '+' + args.rust_toolchain, 'run', '--release', '--manifest-path', manifest, '--', library, cli_marked], env=rust_env)
    print('All requested packaged consumers passed for ' + args.rid)

if __name__ == '__main__':
    main()
