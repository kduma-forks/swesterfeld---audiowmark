#!/usr/bin/env python3
"""Restore the selected variant's CLI archives to ROOT/TARGET for extracted-package validation."""
import argparse
import pathlib
import re
import shutil
import sys
import tempfile
import zipfile
from sources import extract

TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
NAME = re.compile(r'audiowmark-(?P<version>[0-9A-Za-z._+-]+)-(?P<variant>cli|full)-(?P<target>'
                  + '|'.join(TARGETS) + r')\.(?:tar\.gz|zip)')

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

def select(artifacts, variant):
    """Return one (target, archive) per target; any ambiguity is an error, never an overwrite."""
    selected = {}
    for archive in sorted(artifacts.iterdir()):
        match = NAME.fullmatch(archive.name)
        if not match or match['variant'] != variant:
            continue
        target = match['target']
        if target in selected:
            raise RuntimeError(f'duplicate {variant} archive for {target}: {selected[target].name}, {archive.name}')
        selected[target] = archive
    if not selected:
        raise RuntimeError(f'no {variant} archives in {artifacts}')
    return selected

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=pathlib.Path, required=True)
    parser.add_argument('--cli', type=pathlib.Path, required=True)
    parser.add_argument('--variant', choices=('cli', 'full'), default='cli')
    args = parser.parse_args(argv)
    for target, archive in select(args.artifacts, args.variant).items():
        stem = NAME.fullmatch(archive.name)
        expected_root = f"audiowmark-{stem['version']}-{args.variant}-{target}"
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            root = extract_zip(archive, temporary) if archive.name.endswith('.zip') else extract(archive, temporary)
            if root.name != expected_root:
                raise RuntimeError(f'package root {root.name} does not match {archive.name}')
            destination = args.cli / target
            if destination.exists():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, destination, symlinks=True)
            print(destination)

if __name__ == '__main__':
    sys.exit(main())
