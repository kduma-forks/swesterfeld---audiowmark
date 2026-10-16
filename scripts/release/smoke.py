#!/usr/bin/env python3
"""Exercise an extracted standalone CLI without builder audio libraries."""
import argparse
import json
import os
import pathlib
import subprocess
import tempfile
import wave


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=pathlib.Path, required=True)
    args = parser.parse_args()
    cli = args.cli.resolve()
    metadata = json.loads((cli.parent.parent / 'metadata.json').read_text())
    env = os.environ.copy()
    for key in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH'):
        env.pop(key, None)
    env['PATH'] = os.environ.get('SystemRoot', 'C:\\Windows') + '\\System32' if os.name == 'nt' else '/usr/bin:/bin'
    with tempfile.TemporaryDirectory(prefix='audiowmark-cli-package-') as directory:
        work = pathlib.Path(directory)

        def run(*arguments, **kwargs):
            return subprocess.run([str(cli), *map(str, arguments)], cwd=work, env=env, check=True, **kwargs)

        version = run('--version', stdout=subprocess.PIPE, text=True).stdout
        if metadata['version'] not in version:
            raise RuntimeError('CLI/package version mismatch')
        print(version.strip())
        wav = work / 'dźwięk-音.wav'
        marked = work / 'oznaczony-音.wav'
        key = work / 'klucz-音.key'
        payload = '0123456789abcdef0011223344556677'
        run('test-gen-noise', wav, '40', '44100')
        run('gen-key', '--name', 'klucz-音', key)
        run('add', '--key', key, wav, marked, payload)
        run('cmp', '--key', key, marked, payload)
        with wave.open(str(marked), 'rb') as audio:
            if (audio.getnframes(), audio.getnchannels(), audio.getframerate()) != (40 * 44100, 2, 44100):
                raise RuntimeError('CLI changed audio layout')
        # Python passes raw bytes, so Windows CRT text-mode corruption is visible.
        piped = run('add', '-', '-', payload, input=wav.read_bytes(), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if piped.stdout[:4] not in (b'RIFF', b'RF64'):
            raise RuntimeError('CLI stdout is not a binary WAV')
        pipe_wav = work / 'pipe.wav'
        pipe_wav.write_bytes(piped.stdout)
        run('cmp', pipe_wav, payload)
    print('extracted CLI smoke passed')


if __name__ == '__main__':
    main()
