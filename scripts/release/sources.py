#!/usr/bin/env python3
"""Fetch only SHA256-locked archives; prepare source trees and license notices."""
import argparse
import hashlib
import http.client
import json
import pathlib
import shutil
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent

def _variant(variant):
    if variant not in ('cli', 'full'):
        raise ValueError('variant must be cli or full')
    return variant

def lock_files(variant='cli'):
    _variant(variant)
    locks = [ROOT / 'dependencies.lock.json']
    if variant == 'full':
        locks.append(ROOT / 'dependencies-full.lock.json')
    return locks

def entries(variant='cli'):
    selected = []
    names = set()
    filenames = set()
    for lock in lock_files(variant):
        data = json.loads(lock.read_text())
        if data.get('schema') != 1 or not isinstance(data.get('sources'), list):
            raise ValueError('unsupported dependency lock schema: ' + str(lock))
        for entry in data['sources']:
            required = ('name', 'version', 'url', 'filename', 'sha256')
            if any(not isinstance(entry.get(key), str) or not entry[key] for key in required):
                raise ValueError('malformed dependency entry in ' + str(lock))
            if entry['name'] in names or entry['filename'] in filenames:
                raise ValueError('duplicate dependency in effective locks: ' + entry['name'])
            if len(entry['sha256']) != 64 or any(c not in '0123456789abcdef' for c in entry['sha256']):
                raise ValueError('invalid SHA256 for ' + entry['name'])
            names.add(entry['name'])
            filenames.add(entry['filename'])
            selected.append(entry)
    return selected

def effective_manifest(variant='cli'):
    variant = _variant(variant)
    return {
        'schema': 1,
        'variant': variant,
        'locks': [
            {'filename': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in lock_files(variant)
        ],
        'sources': entries(variant),
    }

def write_manifest(path, variant='cli'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(effective_manifest(variant), indent=2) + '\n')

def fetch(entry, cache):
    archive = cache / entry['filename']
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        temporary = archive.with_suffix(archive.suffix + '.part')
        for attempt in range(4):
            try:
                with urllib.request.urlopen(entry['url'], timeout=180) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                break
            except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, http.client.IncompleteRead) as error:
                temporary.unlink(missing_ok=True)
                if (isinstance(error, urllib.error.HTTPError) and error.code not in (408, 429) and error.code < 500) or attempt == 3:
                    raise
                print(f'retrying {entry["filename"]} after {type(error).__name__} (attempt {attempt + 2}/4)', file=sys.stderr)
                time.sleep(2 ** (attempt + 1))
        # Never promote corrupt or incomplete downloads into the source cache.
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != entry['sha256']:
            temporary.unlink()
            raise RuntimeError('SHA256 mismatch: ' + str(archive))
        temporary.replace(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != entry['sha256']:
        raise RuntimeError('SHA256 mismatch: ' + str(archive))
    return archive

def extract(archive, target):
    # Python 3.9 is supported on release builders. Reject paths/links escaping extraction.
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as source:
        members = source.getmembers()
        for member in members:
            candidate = target / member.name
            if not candidate.resolve().is_relative_to(target.resolve()):
                raise RuntimeError('unsafe archive member: ' + member.name)
            if member.issym() or member.islnk():
                link = candidate.parent / member.linkname if member.issym() else target / member.linkname
                if not link.resolve().is_relative_to(target.resolve()):
                    raise RuntimeError('unsafe archive link: ' + member.name)
            if member.isdev():
                raise RuntimeError('unsafe special archive member: ' + member.name)
        source.extractall(target)
    roots = list(target.iterdir())
    if len(roots) != 1 or not roots[0].is_dir():
        raise RuntimeError('expected a single source root: ' + str(archive))
    return roots[0]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=pathlib.Path, required=True)
    parser.add_argument('--sources', type=pathlib.Path)
    parser.add_argument('--licenses', type=pathlib.Path)
    parser.add_argument('--variant', choices=('cli', 'full'), default='cli')
    parser.add_argument('--write-manifest', type=pathlib.Path)
    args = parser.parse_args()
    selected = entries(args.variant)
    for entry in selected:
        archive = fetch(entry, args.cache)
        if not args.sources:
            continue
        destination = args.sources / entry['name']
        if destination.exists():
            shutil.rmtree(destination)
        temporary = args.sources / (entry['name'] + '-extract')
        if temporary.exists():
            shutil.rmtree(temporary)
        source = extract(archive, temporary)
        source.rename(destination)
        temporary.rmdir()
        patches = {'zita-resampler': 'zita-static.patch',
                   'libgpg-error': 'libgpg-error-apple-environ.patch',
                   'vorbis': 'vorbis-apple-linker.patch',
                   'sndfile': 'sndfile-windows-pipe-eof.patch'}
        if entry['name'] in patches:
            subprocess.run(['patch', '-p1', '-i', str(ROOT / 'patches' / patches[entry['name']])], cwd=destination, check=True)
        if args.licenses:
            notices = args.licenses / entry['name']
            notices.mkdir(parents=True, exist_ok=True)
            candidates = [p for p in destination.rglob('*') if p.is_file() and
                          (p.name.startswith(('COPYING', 'LICENSE', 'LICENCE', 'COPYRIGHT', 'AUTHORS', 'NOTICE')))]
            for path in candidates:
                relative = path.relative_to(destination)
                output = notices / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, output)
            if not candidates:
                raise RuntimeError('no license notices for ' + entry['name'])
    if args.licenses:
        write_manifest(args.licenses / 'dependencies.lock.json', args.variant)
        for lock in lock_files(args.variant):
            # dependencies.lock.json is the effective cache/release manifest;
            # keep the base input lock beside it under an unambiguous name.
            name = 'dependencies-base.lock.json' if lock.name == 'dependencies.lock.json' else lock.name
            shutil.copy2(lock, args.licenses / name)
    if args.write_manifest:
        write_manifest(args.write_manifest, args.variant)

if __name__ == '__main__':
    main()
