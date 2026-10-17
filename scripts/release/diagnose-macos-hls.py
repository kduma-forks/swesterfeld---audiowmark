#!/usr/bin/env python3
"""Diagnose the legacy /dev/fd handoff used by HLS temporary files.

Legacy shape (upstream src/hls.cc): a temporary file is handed to ffmpeg as /dev/fd/N and the same
descriptor is then read back through /dev/fd/N. Every variant runs the real bundled ffmpeg and audiowmark:

  named           WAV written to a named temporary file and read back by path (the current design)
  legacy          WAV written through /dev/fd/N of an anonymous temporary file, read back through /dev/fd/N
  legacy-rewound  as legacy, but the parent rewinds the shared descriptor first (observation only)

Exit status is 0 when the named path works and 1 when it fails. The legacy outcome is reported, not asserted.
"""
import argparse
import math
import os
import pathlib
import platform
import subprocess
import sys
import tempfile
import wave

RATE = 44100
SECONDS = 3
EXPECTED_FRAMES = RATE * SECONDS

def write_sine(path):
    with wave.open(str(path), 'wb') as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(RATE)
        samples = bytearray()
        for index in range(EXPECTED_FRAMES):
            value = int(12000 * math.sin(2 * math.pi * 440 * index / RATE)).to_bytes(2, 'little', signed=True)
            samples += value * 2
        audio.writeframes(bytes(samples))

def child_env():
    return {key: value for key, value in os.environ.items() if not key.startswith(('DYLD_', 'LD_'))}

def run(argv, cwd, pass_fds=()):
    # Children run inside the private temporary directory so no stray output can land in the caller's tree.
    return subprocess.run([str(item) for item in argv], cwd=cwd, env=child_env(), pass_fds=tuple(pass_fds),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)

def ffmpeg_to(ffmpeg, source, target, cwd, pass_fds=()):
    # Same arguments as the legacy ff_decode/load_audio_master calls.
    return run([ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', source, '-f', 'wav', target], cwd, pass_fds)

def frames_via(audiowmark, path, cwd, pass_fds=()):
    proc = run([audiowmark, 'test-info', path, 'frames'], cwd, pass_fds)
    frames = proc.stdout.decode('utf-8', 'replace').strip()
    ok = proc.returncode == 0 and frames == str(EXPECTED_FRAMES)
    return ok, proc.returncode, frames, proc.stderr.decode('utf-8', 'replace').strip()

def named(ffmpeg, audiowmark, source, directory):
    handle, path = tempfile.mkstemp(suffix='.wav', dir=directory)
    os.close(handle)
    encode = ffmpeg_to(ffmpeg, source, path, directory)
    ok, rc, frames, err = frames_via(audiowmark, path, directory)
    return dict(ffmpeg_rc=encode.returncode, ffmpeg_stderr=encode.stderr.decode('utf-8', 'replace').strip(),
                ok=encode.returncode == 0 and ok, test_rc=rc, frames=frames, stderr=err)

def legacy(ffmpeg, audiowmark, source, directory, rewind):
    handle = tempfile.TemporaryFile()
    fd = handle.fileno()
    path = f'/dev/fd/{fd}'
    encode = ffmpeg_to(ffmpeg, source, path, directory, pass_fds=(fd,))
    offset = os.lseek(fd, 0, os.SEEK_CUR)
    size = os.fstat(fd).st_size
    if rewind:
        os.lseek(fd, 0, os.SEEK_SET)
    ok, rc, frames, err = frames_via(audiowmark, path, directory, pass_fds=(fd,))
    handle.close()
    return dict(ffmpeg_rc=encode.returncode, ffmpeg_stderr=encode.stderr.decode('utf-8', 'replace').strip(),
                offset_after_ffmpeg=offset, size=size, ok=encode.returncode == 0 and ok, test_rc=rc, frames=frames, stderr=err)

def describe(name, result):
    if result.get('ffmpeg_rc') != 0:
        print(f'{name:15} ffmpeg FAILED (exit {result.get("ffmpeg_rc")})')
        for line in result.get('ffmpeg_stderr', '').splitlines()[-8:]:
            print(f'{"":15} ffmpeg stderr: {line[:300]}')
        return
    extra = ''
    if 'offset_after_ffmpeg' in result:
        extra = f" offset_after_ffmpeg={result['offset_after_ffmpeg']} size={result['size']}"
    status = 'ok' if result['ok'] else 'FAILED'
    print(f'{name:15} ffmpeg ok{extra}; audiowmark test-info frames={result["frames"] or "-"} exit={result["test_rc"]} {status}')
    if not result['ok'] and result['stderr']:
        print(f'{"":15} stderr: {result["stderr"][:300]}')

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bin-dir', type=pathlib.Path, required=True, help='directory with the bundled ffmpeg and audiowmark')
    args = parser.parse_args()
    if os.name == 'nt':
        print('this diagnostic needs POSIX /dev/fd semantics', file=sys.stderr)
        return 2
    # Children run in a temporary working directory, so a relative --bin-dir must be resolved first.
    bin_dir = args.bin_dir.resolve()
    ffmpeg = bin_dir / 'ffmpeg'
    audiowmark = bin_dir / 'audiowmark'
    missing = [str(p) for p in (ffmpeg, audiowmark) if not p.is_file()]
    if missing:
        print('missing executables: ' + ', '.join(missing), file=sys.stderr)
        return 2
    print(f'platform: {platform.system()} {platform.release()} {platform.machine()}')
    with tempfile.TemporaryDirectory(prefix='diagnose-hls-') as directory:
        directory = pathlib.Path(directory)
        banner = run([ffmpeg, '-version'], directory).stdout.decode('utf-8', 'replace').splitlines()
        print('ffmpeg: ' + (banner[0] if banner else 'version unavailable'))
        source = directory / 'source.wav'
        write_sine(source)
        results = {
            'named': named(ffmpeg, audiowmark, source, directory),
            'legacy': legacy(ffmpeg, audiowmark, source, directory, rewind=False),
            'legacy-rewound': legacy(ffmpeg, audiowmark, source, directory, rewind=True),
        }
    for name, result in results.items():
        describe(name, result)
    reproduced = results['legacy']['ffmpeg_rc'] == 0 and not results['legacy']['ok']
    rewinding_fixes = results['legacy-rewound']['ok'] and reproduced
    print(f'legacy /dev/fd handoff reproduced: {"yes" if reproduced else "no"}')
    print(f'rewinding the shared descriptor restores reading: {"yes" if rewinding_fixes else "no"}')
    if not results['named']['ok']:
        print('named temporary file path FAILED', file=sys.stderr)
        return 1
    print('named temporary file path passed')
    return 0

if __name__ == '__main__':
    sys.exit(main())
