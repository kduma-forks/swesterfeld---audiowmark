#!/usr/bin/env python3
"""Fail packaging when an OS floor, private export or dynamic dependency leaks."""
import argparse
import pathlib
import re
import subprocess


def output(*command):
    return subprocess.check_output(command, text=True)


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def audit(target, binary_path, kind, expected):
    binary = str(binary_path)
    exports = set()
    if target.startswith('linux-'):
        machine = output('readelf', '-W', '-h', binary)
        architecture = 'AArch64' if target.endswith('aarch64') else 'Advanced Micro Devices X86-64'
        require(architecture in machine, 'ELF architecture does not match package target')
        dynamic = output('readelf', '-W', '-d', binary)
        needed = re.findall(r'\(NEEDED\).*?\[(.*?)\]', dynamic)
        require('TEXTREL' not in dynamic, 'non-PIC relocation in release library')
        if kind == 'full' or (kind == 'cli' and target.startswith('linux-musl-')):
            require(not needed, 'static release binary has dynamic dependencies')
            require('INTERP' not in output('readelf', '-W', '-l', binary),
                    'static release binary has an interpreter')
        else:
            allow = ({'libc.so.6', 'libm.so.6', 'libpthread.so.0', 'libdl.so.2', 'librt.so.1',
                      'ld-linux-x86-64.so.2', 'ld-linux-aarch64.so.1'} if '-gnu-' in target else
                     {'libc.musl-x86_64.so.1', 'libc.musl-aarch64.so.1', 'libc.so'})
            require(set(needed) <= allow, 'unexpected ELF dependencies: ' + str(needed))
        if '-gnu-' in target:
            versions = re.findall(r'\bGLIBC_(\d+)\.(\d+)(?:\.(\d+))?',
                                  output('readelf', '-W', '--version-info', binary))
            require(all(tuple(map(int, (major, minor, patch or '0'))) <= (2, 28, 0)
                        for major, minor, patch in versions),
                    'ELF requires glibc newer than 2.28')
        if kind == 'sdk':
            symbols = output('nm', '-D', '--defined-only', binary)
            exports = {line.split()[-1].split('@')[0] for line in symbols.splitlines() if line.split()}
            exports = {symbol for symbol in exports if not symbol.startswith('AUDIOWMARK_')}
    elif target.startswith('macos-'):
        architecture = 'arm64' if target.endswith('aarch64') else 'x86_64'
        require(output('lipo', '-archs', binary).strip() == architecture,
                'Mach-O architecture does not match package target')
        needed = [line.strip().split(' (')[0] for line in output('otool', '-L', binary).splitlines()[1:]]
        if kind == 'sdk':
            needed = needed[1:]
        require(all(path in ('/usr/lib/libSystem.B.dylib', '/usr/lib/libc++.1.dylib',
                             '/usr/lib/libobjc.A.dylib')
                    or path.startswith('/System/Library/Frameworks/') for path in needed),
                'unexpected Mach-O deps: ' + str(needed))
        load = output('otool', '-l', binary)
        # Restrict deployment commands only; dylib current_version is independent.
        deployment = re.findall(r'cmd LC_(?:BUILD_VERSION|VERSION_MIN_MACOSX)(.*?)(?=\nLoad command|\Z)',
                                load, re.S)
        require(bool(deployment), 'missing macOS deployment command')
        for command in deployment:
            match = re.search(r'(?:minos|version)\s+(\d+)\.(\d+)', command)
            require(match is not None and tuple(map(int, match.groups())) == (15, 0),
                    'macOS minimum must be 15.0')
        if kind == 'sdk':
            exports = {line.split()[-1].removeprefix('_')
                       for line in output('nm', '-gU', binary).splitlines() if line.split()}
    else:
        require('architecture: i386:x86-64' in output('objdump', '-f', binary),
                'PE architecture must be x64')
        pe = output('objdump', '-p', binary)
        needed = re.findall(r'DLL Name:\s*(\S+)', pe)
        allow = {'kernel32.dll', 'msvcrt.dll', 'advapi32.dll', 'bcrypt.dll', 'ws2_32.dll', 'user32.dll',
                 'ole32.dll', 'shell32.dll', 'shlwapi.dll', 'crypt32.dll', 'secur32.dll', 'ntdll.dll',
                 'psapi.dll'}
        require(set(map(str.lower, needed)) <= allow, 'unexpected PE dependencies: ' + str(needed))
        require('msvcrt.dll' in set(map(str.lower, needed)), 'Windows release must use MSVCRT')
        major = int(re.search(r'MajorSubsystemVersion\s+(\d+)', pe)[1])
        minor = int(re.search(r'MinorSubsystemVersion\s+(\d+)', pe)[1])
        require((major, minor) <= (6, 1), 'PE subsystem exceeds Windows 7')
        for api in ('GetSystemTimePreciseAsFileTime', 'GetOverlappedResultEx', 'SetThreadDescription',
                    'WaitOnAddress', 'WakeByAddressSingle', 'WakeByAddressAll', 'GetTempPath2W'):
            require(not re.search(r'\b' + api + r'\b', pe), 'import requires newer Windows: ' + api)
        if kind == 'sdk':
            table = pe.split('[Ordinal/Name Pointer] Table', 1)
            require(len(table) == 2, 'missing PE export table')
            # Binutils 2.47 includes the absolute ordinal and hint before names.
            names = table[1].split('\n\n', 1)[0]
            exports = set(re.findall(
                r'^\s*\[\s*\d+\]\s+(?:\+base\[\s*\d+\]\s+[0-9a-fA-F]+\s+)?(\S+)\s*$',
                names, re.M))
    if kind == 'sdk':
        require(exports == expected,
                'ABI export mismatch; extra=' + str(sorted(exports - expected)) +
                ' missing=' + str(sorted(expected - exports)))
    print(target, kind, binary_path.name, 'audit passed; OS dependencies:',
          ', '.join(needed) or '(static)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--binary', type=pathlib.Path, required=True, action='append')
    parser.add_argument('--header', type=pathlib.Path)
    parser.add_argument('--kind', choices=['cli', 'sdk', 'full'], default='full')
    args = parser.parse_args()
    if args.kind == 'sdk':
        require(args.header is not None, '--header is required for SDK audits')
        expected = set(re.findall(r'AUDIOWMARK_CALL\s+(audiowmark_\w+)\s*\(', args.header.read_text()))
    else:
        expected = set()
    for binary_path in args.binary:
        audit(args.target, binary_path, args.kind, expected)


if __name__ == '__main__':
    main()
