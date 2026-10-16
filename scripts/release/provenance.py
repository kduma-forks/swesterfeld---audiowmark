"""Obtain the release revision from either a checkout or its source archive."""
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]

def revision():
    metadata = ROOT / 'release-metadata.json'
    if metadata.exists():
        sha = json.loads(metadata.read_text())['commit']
    else:
        sha = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if not re.fullmatch(r'[0-9a-f]{40}',sha):
        raise ValueError('invalid release source commit')
    return sha
