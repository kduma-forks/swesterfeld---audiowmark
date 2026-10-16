#!/usr/bin/env python3
"""Derive validated release/package versions from the exact checked-out tag."""
import argparse
import json
import os
import re
import subprocess
from provenance import revision

SEMVER = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')

def validate(tag):
    version = tag[1:] if tag.startswith('v') else tag
    match = SEMVER.fullmatch(version)
    if not match or (match[4] and any(p.isdigit() and len(p) > 1 and p[0] == '0' for p in match[4].split('.'))):
        raise ValueError('release tag must be SemVer with optional v prefix: ' + tag)
    return version

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag')
    parser.add_argument('--github-output')
    args = parser.parse_args()
    sha = revision()
    event = json.load(open(os.environ['GITHUB_EVENT_PATH'])) if os.environ.get('GITHUB_EVENT_PATH') else {}
    published = os.environ.get('GITHUB_EVENT_NAME') == 'release'
    tag = event['release']['tag_name'] if published else args.tag
    if tag:
        version = validate(tag)
        if published:
            tagged = subprocess.check_output(['git', 'rev-parse', tag + '^{commit}'], text=True).strip()
            if tagged != sha:
                raise ValueError('checkout does not match published release tag')
    else:
        version = '0.0.0-dev.' + sha[:12]
    data = dict(version=version, sha=sha,
                tag=tag or '', publish=str(published).lower())
    print(json.dumps(data, indent=2))
    if args.github_output:
        with open(args.github_output, 'a') as output:
            for key, value in data.items():
                output.write(f'{key}={value}\n')

if __name__ == '__main__':
    main()
