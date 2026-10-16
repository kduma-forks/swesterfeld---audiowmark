#!/usr/bin/env python3
"""Exercise an extracted standalone CLI without builder audio libraries."""
import argparse
import json
import os
import pathlib
import subprocess
import tempfile
import wave


TEST_MSG = 'f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0'
WAV_MSG = '0123456789abcdef0011223344556677'
FIXTURE_NAMES = ('marked.flac', 'marked.mp3', 'marked.ogg', 'marked.opus')


def require_payload(result, expected_bits, expected_key=None):
    matches = result.get('matches')
    if not isinstance(matches, list) or not matches:
        raise RuntimeError('CLI get returned no watermark matches')
    for match in matches:
        if (match.get('bits') == expected_bits and
                (expected_key is None or match.get('key') == expected_key)):
            return
    expected = expected_bits
    if expected_key is not None:
        expected += f' with key {expected_key!r}'
    raise RuntimeError(f'CLI get did not return exact payload {expected}')


def exercise_cli(cli, fixtures):
    cli = pathlib.Path(cli).resolve()
    fixtures = pathlib.Path(fixtures).resolve()
    metadata = json.loads(
        (cli.parent.parent / 'metadata.json').read_text(encoding='utf-8'))
    fixture_paths = [fixtures / name for name in FIXTURE_NAMES]
    missing_fixtures = [str(path) for path in fixture_paths if not path.is_file()]
    if missing_fixtures:
        raise FileNotFoundError(
            'missing CLI smoke fixture(s): ' + ', '.join(missing_fixtures))

    env = os.environ.copy()
    for key in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH',
                'DYLD_FALLBACK_LIBRARY_PATH'):
        env.pop(key, None)
    if os.name == 'nt':
        env['PATH'] = os.environ.get('SystemRoot', 'C:\\Windows') + '\\System32'
    else:
        env['PATH'] = '/usr/bin:/bin'

    with tempfile.TemporaryDirectory(
            prefix='audiowmark-cli-package-') as directory:
        work = pathlib.Path(directory)

        def run(*arguments, **kwargs):
            return subprocess.run(
                [str(cli), *map(str, arguments)], cwd=work, env=env,
                **kwargs)

        version = run('--version', check=True, stdout=subprocess.PIPE,
                      text=True, encoding='utf-8').stdout
        if metadata['version'] not in version:
            raise RuntimeError('CLI/package version mismatch')
        print(version.strip())

        missing = run('get', work / 'missing.wav', check=False,
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if missing.returncode == 0:
            raise RuntimeError('CLI get accepted a missing input file')

        wav = work / 'dźwięk-音.wav'
        marked = work / 'oznaczony-音.wav'
        key = work / 'klucz-音.key'
        run('test-gen-noise', wav, '40', '44100', check=True)
        run('gen-key', '--name', 'klucz-音', key, check=True)
        run('add', '--key', key, wav, marked, WAV_MSG, check=True)
        run('cmp', '--key', key, marked, WAV_MSG, check=True)
        with wave.open(str(marked), 'rb') as audio:
            if (audio.getnframes(), audio.getnchannels(),
                    audio.getframerate()) != (40 * 44100, 2, 44100):
                raise RuntimeError('CLI changed audio layout')

        json_stdout = run(
            'get', '--key', key, '--json', '-', marked, check=True,
            stdout=subprocess.PIPE, text=True, encoding='utf-8').stdout
        require_payload(json.loads(json_stdout), WAV_MSG, 'klucz-音')

        json_file = work / 'wynik-音.json'
        run('get', '--key', key, '--json', json_file, marked, check=True)
        require_payload(
            json.loads(json_file.read_text(encoding='utf-8')),
            WAV_MSG, 'klucz-音')

        # Python passes raw bytes, so Windows CRT text-mode corruption is visible.
        piped = run('add', '-', '-', WAV_MSG, check=True,
                    input=wav.read_bytes(), stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)
        if piped.stdout[:4] not in (b'RIFF', b'RF64'):
            raise RuntimeError('CLI stdout is not a binary WAV')
        pipe_wav = work / 'pipe.wav'
        pipe_wav.write_bytes(piped.stdout)
        run('cmp', pipe_wav, WAV_MSG, check=True)
        pipe_json = run('get', '--json', '-', pipe_wav, check=True,
                        stdout=subprocess.PIPE, text=True,
                        encoding='utf-8').stdout
        require_payload(json.loads(pipe_json), WAV_MSG)

        second_key = work / 'drugi-klucz.key'
        run('gen-key', '--name', 'drugi-klucz', second_key, check=True)
        raw_output_options = (
            '--output-format', 'raw',
            '--raw-rate', '44100',
            '--raw-output-bits', '16',
            '--raw-output-endian', 'little',
            '--raw-output-encoding', 'signed',
            '--raw-channels', '2',
        )
        raw_mark = run(
            'add', '--key', key, wav, '-', WAV_MSG, *raw_output_options,
            check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if raw_mark.returncode != 0:
            stderr = raw_mark.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(
                f'CLI WAV-to-RAW add failed with status '
                f'{raw_mark.returncode}: {stderr}')
        expected_raw_size = 40 * 44100 * 2 * 2
        if len(raw_mark.stdout) != expected_raw_size:
            raise RuntimeError(
                f'CLI RAW output has {len(raw_mark.stdout)} bytes; '
                f'expected {expected_raw_size}')

        raw_input_options = (
            '--input-format', 'raw',
            '--raw-rate', '44100',
            '--raw-input-bits', '16',
            '--raw-input-endian', 'little',
            '--raw-input-encoding', 'signed',
            '--raw-channels', '2',
        )
        raw_wav = work / 'raw-oznaczony-音.wav'
        wav_mark = run(
            'add', '--key', second_key, '-', raw_wav, TEST_MSG,
            *raw_input_options, check=False, input=raw_mark.stdout,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if wav_mark.returncode != 0:
            stderr = wav_mark.stderr.decode('utf-8', errors='replace').strip()
            raise RuntimeError(
                f'CLI RAW-to-WAV add failed with status '
                f'{wav_mark.returncode}: {stderr}')

        first_mark = run(
            'get', '--key', key, '--json', '-', raw_wav, check=True,
            stdout=subprocess.PIPE, text=True, encoding='utf-8').stdout
        require_payload(json.loads(first_mark), WAV_MSG, 'klucz-音')
        second_mark = run(
            'get', '--key', second_key, '--json', '-', raw_wav, check=True,
            stdout=subprocess.PIPE, text=True, encoding='utf-8').stdout
        require_payload(json.loads(second_mark), TEST_MSG, 'drugi-klucz')

        for fixture in fixture_paths:
            fixture_json = run(
                'get', '--json', '-', fixture, check=True,
                stdout=subprocess.PIPE, text=True, encoding='utf-8').stdout
            require_payload(json.loads(fixture_json), TEST_MSG)

    print('extracted CLI smoke passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=pathlib.Path, required=True)
    parser.add_argument('--fixtures', type=pathlib.Path, required=True)
    args = parser.parse_args()
    exercise_cli(args.cli.resolve(), args.fixtures.resolve())


if __name__ == '__main__':
    main()
