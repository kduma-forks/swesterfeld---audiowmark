#!/usr/bin/env python3
"""Restore CLI archives to cli/TARGET for extracted-package validation."""
import argparse
import pathlib
import shutil
import tempfile
import zipfile
from sources import extract

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifacts',type=pathlib.Path,required=True)
parser.add_argument('--cli',type=pathlib.Path,required=True)
args=parser.parse_args()
for archive in sorted(args.artifacts.iterdir()):
    name=archive.name
    if '-cli-' not in name or not name.endswith(('.tar.gz','.zip')): continue
    target=name.split('-cli-',1)[1].removesuffix('.tar.gz').removesuffix('.zip')
    parent=args.cli
    with tempfile.TemporaryDirectory() as directory:
        temporary=pathlib.Path(directory)
        if name.endswith('.zip'):
            with zipfile.ZipFile(archive) as z:
                for member in z.infolist():
                    if not (temporary/member.filename).resolve().is_relative_to(temporary.resolve()): raise RuntimeError('unsafe zip path')
                z.extractall(temporary)
            root=next(temporary.iterdir())
        else:
            root=extract(archive,temporary)
        destination=parent/target
        if destination.exists(): shutil.rmtree(destination)
        shutil.copytree(root,destination,symlinks=True)
        print(destination)
