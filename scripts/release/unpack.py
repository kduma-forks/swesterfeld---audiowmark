#!/usr/bin/env python3
"""Restore release archives for extracted-package validation.

--native ROOT  restores SDK archives to ROOT/TARGET, the shared bindings contract.
--cli ROOT     restores the archives of --variant (cli or full) to ROOT/TARGET.
At least one of the two is required. Any ambiguity (two archives for one target) is an error, never an overwrite.
"""
import argparse
import pathlib
import re
import shutil
import sys
import tempfile
import zipfile
from sources import extract

CLI_TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
SDK_TARGETS = CLI_TARGETS + ('linux-gnu-x86_64', 'linux-gnu-aarch64')
NAME = re.compile(r'audiowmark-(?P<version>[0-9A-Za-z._+-]+)-(?P<kind>cli|full|sdk)-(?P<target>'
                  + '|'.join(SDK_TARGETS) + r')\.(?:tar\.gz|zip)')

def extract_zip(archive, temporary):
    with zipfile.ZipFile(archive) as z:
        for member in z.infolist():
            if not (temporary / member.filename).resolve().is_relative_to(temporary.resolve()):
                raise RuntimeError('unsafe zip path: ' + member.filename)
        z.extractall(temporary)
    roots = list(temporary.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise RuntimeError('expected a single package root: ' + archive.name)
    return roots[0]

def select(artifacts, wanted):
    """wanted(kind, target) -> bool. Returns {target: archive}; two archives for one target are an error."""
    selected = {}
    for archive in sorted(artifacts.iterdir()):
        match = NAME.fullmatch(archive.name)
        if not match or not wanted(match['kind'], match['target']):
            continue
        target = match['target']
        if target in selected:
            raise RuntimeError(f"duplicate {match['kind']} archive for {target}: {selected[target].name}, {archive.name}")
        selected[target] = archive
    return selected

def restore(archive, root_destination, target, kind):
    stem = NAME.fullmatch(archive.name)
    expected_root = f"audiowmark-{stem['version']}-{kind}-{target}"
    with tempfile.TemporaryDirectory() as directory:
        temporary = pathlib.Path(directory)
        root = extract_zip(archive, temporary) if archive.name.endswith('.zip') else extract(archive, temporary)
        if root.name != expected_root:
            raise RuntimeError(f'package root {root.name} does not match {archive.name}')
        destination = root_destination / target
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(root, destination, symlinks=True)
        print(destination)

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--artifacts', type=pathlib.Path, required=True)
    parser.add_argument('--native', type=pathlib.Path)
    parser.add_argument('--cli', type=pathlib.Path)
    parser.add_argument('--variant', choices=('cli', 'full'), default='cli')
    args = parser.parse_args(argv)
    if args.native is None and args.cli is None:
        parser.error('one of --native or --cli is required')
    jobs = []
    if args.native is not None:
        jobs.append((args.native, select(args.artifacts, lambda kind, target: kind == 'sdk'), 'sdk'))
    if args.cli is not None:
        jobs.append((args.cli, select(args.artifacts, lambda kind, target: kind == args.variant), args.variant))
    # A destination may legitimately match nothing (GNU targets have no CLI, full jobs have no SDK); only an
    # empty result across all requested destinations is an error.
    restored = 0
    for root, selected, kind in jobs:
        for target, archive in selected.items():
            restore(archive, root, target, kind)
            restored += 1
    if restored == 0:
        wanted = ', '.join(kind for _, _, kind in jobs)
        raise RuntimeError(f'no {wanted} archives in {args.artifacts}')

if __name__ == '__main__':
    sys.exit(main())
