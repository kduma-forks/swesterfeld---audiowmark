#!/usr/bin/env python3
"""Require all five CLIs and corresponding source/license assets before upload."""
import argparse
import hashlib
import pathlib

TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--version', required=True)
parser.add_argument('--directory', type=pathlib.Path, required=True)
args = parser.parse_args()
expected = {f'audiowmark-{args.version}-cli-{target}' + ('.zip' if target.startswith('win7-') else '.tar.gz')
            for target in TARGETS}
expected.update((f'audiowmark-{args.version}-source.tar.gz', f'audiowmark-{args.version}-licenses.tar.gz'))
actual = {p.name for p in args.directory.iterdir() if p.is_file() and p.name != 'SHA256SUMS'}
if actual != expected:
    raise RuntimeError('release asset mismatch: missing=' + str(sorted(expected - actual)) + ' extra=' + str(sorted(actual - expected)))
lines = []
for name in sorted(expected):
    asset = args.directory / name
    if asset.stat().st_size == 0:
        raise RuntimeError('empty asset ' + name)
    lines.append(hashlib.sha256(asset.read_bytes()).hexdigest() + '  ' + name + '\n')
(args.directory / 'SHA256SUMS').write_text(''.join(lines))
print('verified 7 release assets; wrote SHA256SUMS')
