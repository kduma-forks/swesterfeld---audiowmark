#!/usr/bin/env python3
"""Fail packaging when an OS floor, architecture or dynamic dependency check fails."""
import argparse
import pathlib
import re
import subprocess

def output(*command):
    return subprocess.check_output(command, text=True)

def require(condition, reason):
    if not condition: raise RuntimeError(reason)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', required=True)
    parser.add_argument('--binary', type=pathlib.Path, required=True)
    args = parser.parse_args()
    binary = str(args.binary)
    if args.target.startswith('linux-'):
        machine = output('readelf','-W','-h',binary)
        architecture = 'AArch64' if args.target.endswith('aarch64') else 'Advanced Micro Devices X86-64'
        require(architecture in machine, 'ELF architecture does not match package target')
        dynamic = output('readelf','-W','-d',binary)
        needed = re.findall(r'\(NEEDED\).*?\[(.*?)\]', dynamic)
        require('TEXTREL' not in dynamic, 'non-PIC relocation in release library')
        require(not needed, 'Linux CLI must be fully static')
        require('INTERP' not in output('readelf','-W','-l',binary), 'static CLI has an interpreter')
    elif args.target.startswith('macos-'):
        architecture = 'arm64' if args.target.endswith('aarch64') else 'x86_64'
        require(output('lipo','-archs',binary).strip() == architecture, 'Mach-O architecture does not match package target')
        needed = [line.strip().split(' (')[0] for line in output('otool','-L',binary).splitlines()[1:]]
        require(all(p in ('/usr/lib/libSystem.B.dylib','/usr/lib/libc++.1.dylib','/usr/lib/libobjc.A.dylib')
                    or p.startswith('/System/Library/Frameworks/') for p in needed), 'unexpected Mach-O deps: '+str(needed))
        load = output('otool','-l',binary)
        versions = re.findall(r'(?:minos|version)\s+(\d+)\.(\d+)', load)
        # Restrict deployment commands only; dylib current_version is independent.
        deployment = re.findall(r'cmd LC_(?:BUILD_VERSION|VERSION_MIN_MACOSX)(.*?)(?=\nLoad command|\Z)',load,re.S)
        require(bool(deployment), 'missing macOS deployment command')
        for command in deployment:
            match = re.search(r'(?:minos|version)\s+(\d+)\.(\d+)', command)
            require(match is not None and tuple(map(int,match.groups())) == (15,0), 'macOS minimum must be 15.0')
    else:
        require('architecture: i386:x86-64' in output('objdump','-f',binary), 'PE architecture must be x64')
        pe = output('objdump','-p',binary)
        needed = re.findall(r'DLL Name:\s*(\S+)',pe)
        allow = {'kernel32.dll','msvcrt.dll','advapi32.dll','bcrypt.dll','ws2_32.dll','user32.dll',
                 'ole32.dll','shell32.dll','shlwapi.dll','crypt32.dll','secur32.dll','ntdll.dll'}
        require(set(map(str.lower,needed)) <= allow, 'unexpected PE dependencies: '+str(needed))
        require('msvcrt.dll' in set(map(str.lower,needed)), 'Windows release must use MSVCRT')
        major = int(re.search(r'MajorSubsystemVersion\s+(\d+)',pe)[1])
        minor = int(re.search(r'MinorSubsystemVersion\s+(\d+)',pe)[1])
        require((major,minor) <= (6,1), 'PE subsystem exceeds Windows 7')
        for api in ('GetSystemTimePreciseAsFileTime','GetOverlappedResultEx','SetThreadDescription','WaitOnAddress',
                    'WakeByAddressSingle','WakeByAddressAll','GetTempPath2W'):
            require(not re.search(r'\b'+api+r'\b',pe), 'import requires newer Windows: '+api)
    print(args.target, 'CLI audit passed; OS dependencies:', ', '.join(needed) or '(static)')

if __name__ == '__main__':
    main()
