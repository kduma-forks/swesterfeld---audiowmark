#!/usr/bin/env python3
"""Bundle the exact checkout, all locked dependency sources, recipes and notices."""
import argparse
import json
import pathlib
import shutil
import subprocess
import tarfile
from sources import entries, fetch

ROOT=pathlib.Path(__file__).resolve().parents[2]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True)
    parser.add_argument('--work',type=pathlib.Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    stage=args.work/f'audiowmark-{args.version}-source'
    if stage.exists(): shutil.rmtree(stage)
    stage.mkdir(parents=True)
    # CI checks out the metadata job's exact commit; git archive includes all tracked release recipes.
    source_tar=args.work/'project.tar'
    subprocess.run(['git','archive','--format=tar','--output',str(source_tar.resolve()),'HEAD'],cwd=ROOT,check=True)
    project=stage/'audiowmark';project.mkdir()
    with tarfile.open(source_tar) as archive: archive.extractall(project)
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    (project/'release-metadata.json').write_text(json.dumps(dict(version=args.version,commit=sha),indent=2)+'\n')
    dependencies=stage/'dependencies';dependencies.mkdir()
    for entry in entries():
        archive=fetch(entry,args.work/'downloads')
        shutil.copy2(archive,dependencies/archive.name)
    shutil.copy2(ROOT/'scripts/release/dependencies.lock.json',dependencies/'dependencies.lock.json')
    shutil.copytree(ROOT/'scripts/release',stage/'build-scripts',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'COPYING',stage/'COPYING')
    (stage/'metadata.json').write_text(json.dumps(dict(version=args.version,
       commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
       dependencies=entries()),indent=2)+'\n')
    (stage/'BUILDING.txt').write_text('The audiowmark directory is the exact release commit. Dependency archives are verified by build-scripts/dependencies.lock.json.\n'
      'Set SOURCE_CACHE to the absolute dependencies directory, TARGET and RELEASE_WORK to matching native platform paths, and VERSION to the metadata version.\n'
      'Run audiowmark/scripts/release/build.sh in the documented toolchain; see docs/releasing.md and images.lock.json.\n'
      'Audio dependencies are built from these sources, including the checked-in zita static patch.\n'
      'GCC runtime redistribution uses the GCC Runtime Library Exception. Its notices accompany binaries; the compiler itself is not bundled.\n')
    with tarfile.open(args.output/(stage.name+'.tar.gz'),'w:gz') as archive: archive.add(stage,arcname=stage.name)
    # The standalone notices archive is the union of all locked dependency license files.
    notices=args.work/f'audiowmark-{args.version}-licenses'
    subprocess.run(['python3',str(ROOT/'scripts/release/sources.py'),'--cache',str(args.work/'downloads'),
                    '--sources',str(args.work/'sources'),'--licenses',str(notices)],check=True)
    shutil.copy2(ROOT/'COPYING',notices/'audiowmark-COPYING')
    shutil.copytree(ROOT/'scripts/release/licenses',notices/'toolchain',dirs_exist_ok=True)
    with tarfile.open(args.output/(notices.name+'.tar.gz'),'w:gz') as archive: archive.add(notices,arcname=notices.name)

if __name__=='__main__': main()
