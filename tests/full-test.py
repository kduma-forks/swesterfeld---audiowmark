#!/usr/bin/env python3
"""Regression tests for the full audiowmark package (audiowmark, videowmark, ffmpeg, ffprobe).

    full-test.py --bin-dir DIR [--smoke] [--keep] [--only NAME]

DIR must contain the four executables (with .exe on Windows). The tests need no Bash and no
tools from PATH: the child processes get an empty PATH, so videowmark and audiowmark have to find
ffmpeg and ffprobe beside themselves. Python is only the test driver. --smoke runs a short subset
for checks of an already extracted release package.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

PAYLOAD = '0123456789abcdef0011223344556677'
OTHER_PAYLOAD = 'f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0'
SECONDS = 70                      # at least one complete data block for a 128-bit message
FIXTURE = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'video-vp8.webm'
WINDOWS = os.name == 'nt'
TIMEOUT = 900


class Skip(Exception):
    pass


class Context:
    """Paths and helpers shared by all tests."""

    def __init__(self, bin_dir, root):
        suffix = '.exe' if WINDOWS else ''
        self.bin_dir = bin_dir
        self.audiowmark = str(bin_dir / ('audiowmark' + suffix))
        self.videowmark = str(bin_dir / ('videowmark' + suffix))
        self.ffmpeg = str(bin_dir / ('ffmpeg' + suffix))
        self.ffprobe = str(bin_dir / ('ffprobe' + suffix))
        self.root = root
        self.tmp = root / 'tmp'          # TMPDIR/TEMP of every child; must stay empty
        self.media_dir = root / 'media'
        self.empty_path = root / 'empty-path'
        for directory in (self.tmp, self.media_dir, self.empty_path):
            directory.mkdir()
        self.media_cache = {}
        self.counter = 0

    def env(self):
        env = {k: v for k, v in os.environ.items()
               if k not in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FALLBACK_LIBRARY_PATH', 'AUDIOWMARK_BUNDLED_TOOLS')}
        env['PATH'] = str(self.empty_path)
        for key in ('TMPDIR', 'TMP', 'TEMP'):
            env[key] = str(self.tmp)
        if WINDOWS:
            env['PATH'] = str(self.empty_path)
            env.setdefault('SystemRoot', os.environ.get('SystemRoot', 'C:\\Windows'))
        return env

    def run(self, argv, cwd=None, expect=0, timeout=TIMEOUT, input=None):
        """Run a command; expect=None accepts any exit code, expect='fail' any nonzero one."""
        proc = subprocess.run([str(a) for a in argv], cwd=cwd, env=self.env(), input=input, timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.out = proc.stdout.decode('utf-8', 'replace')
        proc.err = proc.stderr.decode('utf-8', 'replace')
        ok = (proc.returncode != 0) if expect == 'fail' else (expect is None or proc.returncode == expect)
        if not ok:
            raise AssertionError('%s exited with %d (expected %s)\nstdout:\n%s\nstderr:\n%s' % (
                ' '.join(map(str, argv)), proc.returncode, expect, proc.out[-2000:], proc.err[-4000:]))
        return proc

    def videowmark_run(self, *args, **kwargs):
        return self.run([self.videowmark, *args], **kwargs)

    def new_dir(self, name='case'):
        self.counter += 1
        directory = self.root / ('%s-%d' % (name, self.counter))
        directory.mkdir()
        return directory

    def assert_tmp_clean(self):
        leftovers = sorted(p.name for p in self.tmp.iterdir())
        if leftovers:
            raise AssertionError('temporary files left in TMPDIR: %s' % leftovers)

    # ------------------------------------------------------------------ media
    def probe(self, path):
        out = self.run([self.ffprobe, '-v', 'error', '-of', 'json', '-show_entries',
                        'stream=index,codec_type,codec_name,bit_rate,start_time:format=duration', path]).out
        return json.loads(out)

    def audio_stream(self, path):
        streams = [s for s in self.probe(path)['streams'] if s['codec_type'] == 'audio']
        if len(streams) != 1:
            raise AssertionError('%s: expected one audio stream, got %d' % (path, len(streams)))
        return streams[0]

    def av_offset(self, path):
        """audio start_time minus video start_time in seconds (None if the container has no start times)."""
        starts = {}
        for stream in self.probe(path)['streams']:
            try:
                starts.setdefault(stream['codec_type'], float(stream['start_time']))
            except (KeyError, ValueError):
                pass
        if 'audio' in starts and 'video' in starts:
            return starts['audio'] - starts['video']
        return None

    def assert_same_av_offset(self, before, after, limit=0.100):
        offset_before, offset_after = self.av_offset(before), self.av_offset(after)
        if offset_before is None or offset_after is None:
            raise AssertionError('missing stream start times in %s / %s' % (before, after))
        if abs(offset_before - offset_after) > limit:
            raise AssertionError('relative A/V offset changed from %.3fs to %.3fs' % (offset_before, offset_after))

    def duration(self, path):
        return float(self.probe(path)['format']['duration'])

    def video_md5(self, path):
        out = self.run([self.ffmpeg, '-v', 'error', '-nostdin', '-i', path, '-map', '0:v:0', '-c', 'copy',
                        '-f', 'md5', '-']).out
        return out.strip()

    def make_wav(self, path, seconds=SECONDS):
        self.run([self.audiowmark, 'test-gen-noise', path, str(seconds), '44100'])

    def make_video(self, path, audio_args, seconds=SECONDS, video='mpeg4', extra=(), wav=None):
        if wav is None:
            wav = self.media_dir / ('noise-%d.wav' % seconds)
            if not wav.exists():
                self.make_wav(wav, seconds)
        common = [self.ffmpeg, '-v', 'error', '-nostdin', '-y']
        if video == 'webm':
            command = common + ['-i', FIXTURE, '-i', wav, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy']
        else:
            codec = ['-c:v', 'mpeg4', '-q:v', '5'] if video == 'mpeg4' else ['-c:v', 'ffv1']
            command = common + ['-i', wav, '-filter_complex', 'testsrc=s=64x48:r=5:d=%d[v]' % seconds,
                                '-map', '[v]', '-map', '0:a'] + codec
        self.run(command + list(audio_args) + list(extra) + [path])
        return path

    def media(self, key):
        if key not in self.media_cache:
            ext, video, audio = MATRIX[key]
            if video == 'webm' and not FIXTURE.exists():
                raise AssertionError('missing required VP8 fixture %s' % FIXTURE)
            self.media_cache[key] = self.make_video(self.media_dir / ('src-' + key + ext), audio, video=video)
        return self.media_cache[key]

    # ------------------------------------------------------------ watermarks
    def detect(self, path, *options):
        """Text of `videowmark get`."""
        return self.videowmark_run(*options, 'get', path).out

    def assert_marked(self, path, payload=PAYLOAD, *options):
        out = self.detect(path, *options)
        if payload not in out:
            raise AssertionError('%s: watermark %s not found:\n%s' % (path, payload, out[-1500:]))

    def assert_not_marked(self, path, payload=PAYLOAD, *options):
        out = self.detect(path, *options)
        if payload in out:
            raise AssertionError('%s: unexpected watermark %s' % (path, payload))


# codec and container combinations: (extension, video, audio encoder arguments)
# The sources are made from white noise and videowmark encodes the audio a second time with the
# same bit rate, so the bit rates are high enough for the watermark to survive both generations.
MATRIX = {
    'mp4-aac':     ('.mp4',  'mpeg4', ['-c:a', 'aac', '-b:a', '256k']),
    'avi-mp3':     ('.avi',  'mpeg4', ['-c:a', 'libmp3lame', '-b:a', '256k']),
    'mkv-opus':    ('.mkv',  'mpeg4', ['-c:a', 'libopus', '-b:a', '192k']),
    'mkv-vorbis':  ('.mkv',  'mpeg4', ['-c:a', 'libvorbis', '-b:a', '256k']),
    'mkv-flac':    ('.mkv',  'ffv1',  ['-c:a', 'flac']),
    'mkv-pcm':     ('.mkv',  'mpeg4', ['-c:a', 'pcm_s16le']),
    'mov-pcm':     ('.mov',  'mpeg4', ['-c:a', 'pcm_s24le']),
    'webm-opus':   ('.webm', 'webm',  ['-c:a', 'libopus', '-b:a', '192k']),
    'webm-vorbis': ('.webm', 'webm',  ['-c:a', 'libvorbis', '-b:a', '256k']),
}
SMOKE_MATRIX = ('mp4-aac', 'avi-mp3', 'webm-opus', 'webm-vorbis', 'mkv-flac', 'mkv-pcm')
EXPECTED_AUDIO = {'aac': 'aac', 'mp3': 'mp3', 'opus': 'opus', 'vorbis': 'vorbis', 'flac': 'flac',
                  'pcm_s16le': 'pcm_s16le', 'pcm_s24le': 'pcm_s24le'}

TESTS = []


def test(smoke=False, posix_only=False, windows_only=False):
    def register(function):
        TESTS.append((function.__name__.replace('_', '-'), function, smoke, posix_only, windows_only))
        return function
    return register


def lossy(codec):
    return codec in ('aac', 'mp3', 'opus', 'vorbis')


def check_roundtrip(ctx, key):
    src = ctx.media(key)
    ext = MATRIX[key][0]
    work = ctx.new_dir('roundtrip-' + key)
    out = work / ('out' + ext)
    proc = ctx.videowmark_run('add', src, out, PAYLOAD)
    if 'Audio Codec:' not in proc.err:
        raise AssertionError('missing "Audio Codec:" message:\n' + proc.err)
    ctx.assert_tmp_clean()
    if sorted(p.name for p in work.iterdir()) != ['out' + ext]:
        raise AssertionError('unexpected files in output directory: %s' % [p.name for p in work.iterdir()])

    streams = ctx.probe(out)['streams']
    kinds = sorted(s['codec_type'] for s in streams)
    if kinds != ['audio', 'video']:
        raise AssertionError('output streams: %s' % kinds)
    before, after = ctx.audio_stream(src), ctx.audio_stream(out)
    if before['codec_name'] != after['codec_name']:
        raise AssertionError('audio codec changed: %s -> %s' % (before['codec_name'], after['codec_name']))
    if abs(ctx.duration(src) - ctx.duration(out)) > 0.3:
        raise AssertionError('duration changed: %s -> %s' % (ctx.duration(src), ctx.duration(out)))
    ctx.assert_same_av_offset(src, out)
    if lossy(before['codec_name']) and before.get('bit_rate', 'N/A').isdigit() and after.get('bit_rate', 'N/A').isdigit():
        ratio = float(after['bit_rate']) / float(before['bit_rate'])
        if not 0.5 < ratio < 2.0:
            raise AssertionError('audio bit rate %s -> %s' % (before['bit_rate'], after['bit_rate']))
    if ctx.video_md5(src) != ctx.video_md5(out):
        raise AssertionError('video stream was not copied unchanged')
    ctx.assert_marked(out)
    ctx.assert_not_marked(src)


def codec_test(key):
    def run(ctx):
        check_roundtrip(ctx, key)
    run.__name__ = 'roundtrip_' + key.replace('-', '_')
    return run


for _key in MATRIX:
    TESTS.append(('roundtrip-' + _key, codec_test(_key), _key in SMOKE_MATRIX, False, False))


# --------------------------------------------------------------------- command line
@test(smoke=True)
def help_and_usage(ctx):
    proc = ctx.videowmark_run('-h')
    if not proc.out.startswith('usage: videowmark <command>') or '--strength <s>' not in proc.out:
        raise AssertionError(proc.out)
    ctx.videowmark_run('--help')
    ctx.videowmark_run('-qh')
    for args in ([], ['--bogus'], ['--key'], ['add', 'a', 'b'], ['get'], ['frob', 'x'], ['-z', 'get', 'x'],
                 ['--verbose=1', 'get', 'x'], ['probe']):
        proc = ctx.videowmark_run(*args, expect='fail')
        if 'videowmark' not in proc.err:
            raise AssertionError('no diagnostic for %s: %r' % (args, proc.err))
    if 'error parsing command line arguments' not in ctx.videowmark_run(expect='fail').err:
        raise AssertionError('missing usage message')


@test(smoke=True)
def probe_output(ctx):
    src = ctx.media('mp4-aac')
    line = ctx.videowmark_run('probe', src).out.strip()
    if not re.fullmatch(re.escape(str(src)) + r' -c:a aac -ab \d+', line):
        raise AssertionError(line)
    for key, codec in (('mkv-opus', 'libopus'), ('avi-mp3', 'mp3'), ('mkv-flac', 'flac')):
        line = ctx.videowmark_run('probe', ctx.media(key)).out.strip()
        if ' -c:a %s' % codec not in line:
            raise AssertionError('%s: %s' % (key, line))


@test(smoke=True)
def option_positions(ctx):
    src = ctx.media('mp4-aac')
    for args in (['-q', 'probe', src], ['probe', src, '-q'], ['probe', '-qv', src], ['--qui', 'probe', src],
                 ['--', 'probe', src], ['-v', '-q', 'probe', src]):
        ctx.videowmark_run(*args)
    work = ctx.new_dir('options')
    key = work / 'test.key'
    ctx.run([ctx.audiowmark, 'gen-key', key])
    out_a, out_b, out_c = work / 'a.mp4', work / 'b.mp4', work / 'c.mp4'
    quiet = ctx.videowmark_run('add', '--key=' + str(key), '--str', '12', src, out_a, PAYLOAD, '-q')
    if 'Audio Codec' in quiet.err:
        raise AssertionError('-q must silence information messages')
    ctx.videowmark_run('-q', '--key', key, 'add', src, out_b, PAYLOAD)
    ctx.videowmark_run('add', '-qv', '--', src, out_c, PAYLOAD)
    ctx.assert_marked(out_a, PAYLOAD, '--key', str(key))
    ctx.assert_marked(out_b, PAYLOAD, '--key', str(key))
    ctx.assert_not_marked(out_a)      # the default key does not find a watermark made with another key
    ctx.assert_marked(out_c)
    ctx.assert_tmp_clean()


# ---------------------------------------------------------------------- rejected input
@test(smoke=True)
def input_validation(ctx):
    src = ctx.media('mp4-aac')
    work = ctx.new_dir('validation')

    def rejected(args, message, outputs=()):
        proc = ctx.videowmark_run(*args, expect='fail')
        if message not in proc.err:
            raise AssertionError('%s: expected %r in:\n%s' % (args, message, proc.err))
        for output in outputs:
            if pathlib.Path(output).exists():
                raise AssertionError('unexpected output %s' % output)
        if sorted(p.name for p in work.iterdir()):
            raise AssertionError('leftover files: %s' % sorted(p.name for p in work.iterdir()))
        ctx.assert_tmp_clean()

    rejected(['add', work / 'missing.mp4', work / 'o.mp4', PAYLOAD], 'ffprobe', [work / 'o.mp4'])
    rejected(['get', work / 'missing.mp4'], 'ffprobe')
    rejected(['add', src, work / 'o.mkv', PAYLOAD], "extension must match ('.mp4' vs. '.mkv')", [work / 'o.mkv'])
    rejected(['add', src, work / 'o.mp4', 'xyz'], 'hexadecimal', [work / 'o.mp4'])

    audio_only = ctx.media_dir / 'audio-only.m4a'
    video_only = ctx.media_dir / 'video-only.mp4'
    two_audio = ctx.media_dir / 'two-audio.mkv'
    wav = ctx.media_dir / ('noise-%d.wav' % SECONDS)
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', src, '-vn', '-c:a', 'copy', audio_only])
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', src, '-an', '-c:v', 'copy', video_only])
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', src, '-i', wav, '-map', '0:v', '-map', '0:a', '-map', '1:a',
             '-c:v', 'copy', '-c:a', 'aac', two_audio])
    rejected(['add', audio_only, work / 'o.m4a', PAYLOAD], 'audio=1:video=0', [work / 'o.m4a'])
    rejected(['add', video_only, work / 'o.mp4', PAYLOAD], 'audio=0:video=1', [work / 'o.mp4'])
    rejected(['add', two_audio, work / 'o.mkv', PAYLOAD], 'audio=2:video=1', [work / 'o.mkv'])
    rejected(['get', two_audio], 'audio=2:video=1')


@test(smoke=True)
def unsupported_audio_codec(ctx):
    """No fallback: ac3 cannot be added, but it can still be detected."""
    src = ctx.make_video(ctx.media_dir / 'ac3.mkv', ['-c:a', 'ac3', '-b:a', '192k'])
    work = ctx.new_dir('unsupported')
    proc = ctx.videowmark_run('add', src, work / 'out.mkv', PAYLOAD, expect='fail')
    if "unsupported audio codec 'ac3'" not in proc.err:
        raise AssertionError(proc.err)
    if list(work.iterdir()):
        raise AssertionError('files left behind: %s' % list(work.iterdir()))
    ctx.assert_tmp_clean()
    ctx.assert_not_marked(src)


@test(posix_only=True)
def missing_encoder(ctx):
    """An ffmpeg without the MP3 encoder must be an error before any work is done."""
    real = ctx.ffmpeg
    bin_dir = ctx.new_dir('no-lame-bin')
    for name in ('videowmark', 'audiowmark', 'ffprobe'):
        source = pathlib.Path(ctx.bin_dir / name)
        try:
            os.link(source, bin_dir / name)
        except OSError:
            shutil.copy2(source, bin_dir / name)
    wrapper = bin_dir / 'ffmpeg'
    # only shell built-ins: the tests run with an empty PATH
    wrapper.write_text('#!/bin/sh\ncase " $* " in\n  *" -encoders "*)\n    "%s" "$@" | while IFS= read -r line; do\n'
                       '      case "$line" in *libmp3lame*) ;; *) printf \'%%s\\n\' "$line" ;; esac\n    done ;;\n'
                       '  *) exec "%s" "$@" ;;\nesac\n' % (real, real))
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    work = ctx.new_dir('missing-encoder')
    proc = ctx.run([bin_dir / 'videowmark', 'add', ctx.media('avi-mp3'), work / 'out.avi', PAYLOAD], expect='fail')
    if "audio encoder 'libmp3lame'" not in proc.err or 'not available' not in proc.err:
        raise AssertionError(proc.err)
    if list(work.iterdir()):
        raise AssertionError('files left behind')
    ctx.assert_tmp_clean()
    # the other codecs keep working with that ffmpeg
    ctx.run([bin_dir / 'videowmark', 'probe', ctx.media('mp4-aac')])


# --------------------------------------------------------------- output file handling
@test(smoke=True)
def atomic_overwrite_and_failure(ctx):
    src = ctx.media('mp4-aac')
    work = ctx.new_dir('overwrite')
    out = work / 'out.mp4'
    original = b'previous output that must survive any failure'
    out.write_bytes(original)

    # fails after the audio was extracted: audiowmark cannot read the key
    proc = ctx.videowmark_run('--key', work / 'missing.key', 'add', src, out, PAYLOAD, expect='fail')
    if 'watermark generation failed' not in proc.err:
        raise AssertionError(proc.err)
    if out.read_bytes() != original:
        raise AssertionError('existing output was modified by a failed run')
    if sorted(p.name for p in work.iterdir()) != ['out.mp4']:
        raise AssertionError('leftover files: %s' % sorted(p.name for p in work.iterdir()))
    ctx.assert_tmp_clean()

    # the last step fails: the destination is a directory
    target = work / 'directory.mp4'
    target.mkdir()
    (target / 'keep.txt').write_text('keep')
    ctx.videowmark_run('add', src, target, PAYLOAD, expect='fail')
    if (target / 'keep.txt').read_text() != 'keep' or sorted(p.name for p in work.iterdir()) != ['directory.mp4', 'out.mp4']:
        raise AssertionError('failed run changed the output directory: %s' % sorted(p.name for p in work.iterdir()))
    ctx.assert_tmp_clean()

    # success replaces the old file (-y behavior of the former script)
    ctx.videowmark_run('add', src, out, PAYLOAD)
    if out.read_bytes() == original:
        raise AssertionError('existing output was not replaced')
    ctx.assert_marked(out)
    if sorted(p.name for p in work.iterdir()) != ['directory.mp4', 'out.mp4']:
        raise AssertionError('leftover files: %s' % sorted(p.name for p in work.iterdir()))
    ctx.assert_tmp_clean()


@test(smoke=True)
def same_file_rejected(ctx):
    work = ctx.new_dir('same-file')
    src = work / 'in.mp4'
    shutil.copy2(ctx.media('mp4-aac'), src)
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    proc = ctx.videowmark_run('add', src, src, PAYLOAD, expect='fail')
    if 'different files' not in proc.err:
        raise AssertionError(proc.err)
    alias = work / 'alias.mp4'
    try:
        os.link(src, alias)
    except OSError:
        alias = None
    if alias is not None:
        ctx.videowmark_run('add', src, alias, PAYLOAD, expect='fail')
        ctx.videowmark_run('add', work / '.' / 'in.mp4', work / '..' / work.name / 'alias.mp4', PAYLOAD, expect='fail')
    if hashlib.sha256(src.read_bytes()).hexdigest() != digest:
        raise AssertionError('input file was modified')
    ctx.assert_tmp_clean()


@test(smoke=True)
def unicode_and_special_names(ctx):
    work = ctx.new_dir('unicode') / 'wejście ü 音 dir'
    work.mkdir()
    src = work / 'film źdźbło-音.mp4'
    out = work / 'wynik źdźbło-音.mp4'
    shutil.copy2(ctx.media('mp4-aac'), src)
    key = work / 'klucz-音.key'
    ctx.run([ctx.audiowmark, 'gen-key', '--name', 'klucz-音', key])
    ctx.videowmark_run('add', '--key', key, src, out, PAYLOAD)
    ctx.assert_marked(out, PAYLOAD, '--key', str(key))
    ctx.assert_not_marked(out)
    ctx.assert_tmp_clean()

    # names that look like options (or URLs) are only file names
    dash = work / 'cwd'
    dash.mkdir()
    shutil.copy2(ctx.media('mp4-aac'), dash / '-dash.mp4')
    ctx.videowmark_run('add', '--', '-dash.mp4', '-dash-out.mp4', PAYLOAD, cwd=dash)
    ctx.videowmark_run('get', '--', '-dash-out.mp4', cwd=dash)
    if PAYLOAD not in ctx.videowmark_run('get', '--', '-dash-out.mp4', cwd=dash).out:
        raise AssertionError('watermark not found in -dash-out.mp4')
    if not WINDOWS:
        shutil.copy2(ctx.media('mp4-aac'), dash / 'concat:x.mp4')
        ctx.videowmark_run('add', 'concat:x.mp4', 'subfile:y.mp4', PAYLOAD, cwd=dash)
        ctx.videowmark_run('probe', 'concat:x.mp4', cwd=dash)
    ctx.assert_tmp_clean()


@test()
def stream_metadata_is_not_trusted(ctx):
    """Tags are file content: they must not influence the codec or the ffmpeg options."""
    src = ctx.media_dir / 'tags.mp4'
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', ctx.media('mp4-aac'), '-c', 'copy',
             '-metadata:s:a:0', 'title=x|codec_type=audio|codec_name=libopus|bit_rate=1 -report',
             '-metadata:s:a:0', 'handler_name=|stream|codec_type=video|codec_name=flac',
             src])
    work = ctx.new_dir('tags')
    ctx.videowmark_run('add', src, work / 'out.mp4', PAYLOAD, cwd=work)
    if ctx.audio_stream(work / 'out.mp4')['codec_name'] != 'aac':
        raise AssertionError('stream tags changed the encoder')
    ctx.assert_marked(work / 'out.mp4')
    # "-report" would have written ffmpeg-<date>.log into the working directory
    if sorted(p.name for p in work.iterdir()) != ['out.mp4']:
        raise AssertionError('unexpected files: %s' % sorted(p.name for p in work.iterdir()))
    ctx.assert_tmp_clean()


@test()
def parallel_runs(ctx):
    src = ctx.media('mp4-aac')
    work = ctx.new_dir('parallel')
    outs = [work / ('out%d.mp4' % i) for i in range(3)]
    procs = [subprocess.Popen([ctx.videowmark, 'add', str(src), str(o), PAYLOAD], env=ctx.env(),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) for o in outs]
    for proc in procs:
        stdout, stderr = proc.communicate(timeout=TIMEOUT)
        if proc.returncode != 0:
            raise AssertionError(stderr.decode('utf-8', 'replace'))
    for out in outs:
        ctx.assert_marked(out)
    ctx.assert_tmp_clean()
    if sorted(p.name for p in work.iterdir()) != sorted(o.name for o in outs):
        raise AssertionError('leftover files')


@test(posix_only=True)
def interrupt_cleans_up(ctx):
    wav = ctx.media_dir / 'noise-900.wav'
    ctx.make_wav(wav, 900)
    long_video = ctx.make_video(ctx.media_dir / 'long.mp4', ['-c:a', 'aac', '-b:a', '128k'], seconds=900, wav=wav)
    wav.unlink()
    work = ctx.new_dir('interrupt')
    proc = subprocess.Popen([ctx.videowmark, 'add', str(long_video), str(work / 'out.mp4'), PAYLOAD], env=ctx.env(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 120
    while time.time() < deadline and proc.poll() is None and not list(ctx.tmp.iterdir()):
        time.sleep(0.02)
    if proc.poll() is not None:
        raise Skip('videowmark finished before it could be interrupted')
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise AssertionError('videowmark did not stop after SIGINT')
    if proc.returncode == 0:
        raise Skip('videowmark finished before the signal arrived')
    ctx.assert_tmp_clean()
    if list(work.iterdir()):
        raise AssertionError('interrupted run left files: %s' % list(work.iterdir()))


# ------------------------------------------------------------------------- A/V offsets
def make_offset_video(ctx, path, audio_late):
    """Video and AAC audio whose start times differ by 0.4 seconds (audio later, or earlier if not audio_late)."""
    wav = ctx.media_dir / ('noise-%d.wav' % SECONDS)
    if not wav.exists():
        ctx.make_wav(wav)
    if audio_late:
        ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-itsoffset', '0.4', '-i', wav,
                 '-filter_complex', 'testsrc=s=64x48:r=5:d=%d[v]' % SECONDS, '-map', '[v]', '-map', '0:a',
                 '-c:v', 'mpeg4', '-q:v', '5', '-c:a', 'aac', '-b:a', '256k', path])
    else:
        video = ctx.media_dir / 'offset-video-only.mkv'
        if not video.exists():
            ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-filter_complex', 'testsrc=s=64x48:r=5:d=%d[v]' % SECONDS,
                     '-map', '[v]', '-c:v', 'mpeg4', '-q:v', '5', video])
        ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-itsoffset', '0.4', '-i', video, '-i', wav,
                 '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', path])
    return path


def check_av_offset(ctx, ext, audio_late):
    src = make_offset_video(ctx, ctx.media_dir / ('offset-%s%s' % ('late' if audio_late else 'early', ext)), audio_late)
    expected = 0.4 if audio_late else -0.4
    offset = ctx.av_offset(src)
    if offset is None or abs(offset - expected) > 0.06:
        raise AssertionError('test input has a relative A/V offset of %r, expected about %.1f' % (offset, expected))
    work = ctx.new_dir('av-offset')
    out = work / ('out' + ext)
    ctx.videowmark_run('add', src, out, PAYLOAD)
    ctx.assert_same_av_offset(src, out, 0.100)
    ctx.assert_marked(out)
    ctx.assert_tmp_clean()


@test(smoke=True)
def av_offset_audio_late_mkv(ctx):
    check_av_offset(ctx, '.mkv', True)


@test(smoke=True)
def av_offset_audio_early_mkv(ctx):
    check_av_offset(ctx, '.mkv', False)


@test()
def av_offset_audio_late_mp4(ctx):
    check_av_offset(ctx, '.mp4', True)


@test()
def av_offset_audio_early_mp4(ctx):
    check_av_offset(ctx, '.mp4', False)


@test(posix_only=True)
def probe_bit_rate_values(ctx):
    """Only positive bit rates an encoder can use are passed on (0, N/A and absurd values mean: encoder default)."""
    bin_dir = ctx.new_dir('fake-ffprobe')
    source = pathlib.Path(ctx.bin_dir / 'videowmark')
    try:
        os.link(source, bin_dir / 'videowmark')
    except OSError:
        shutil.copy2(source, bin_dir / 'videowmark')
    probe = bin_dir / 'ffprobe'
    probe.write_text('#!/bin/sh\nprintf "stream|codec_name=video|codec_type=video|start_time=0.000000\\n"\n'
                     'printf "stream|codec_name=$FAKE_CODEC|codec_type=audio|bit_rate=$FAKE_BIT_RATE|start_time=0.000000\\n"\n')
    probe.chmod(probe.stat().st_mode | stat.S_IXUSR)
    cases = [('aac', '128000', ' -c:a aac -ab 128000'), ('aac', '0', ' -c:a aac'), ('aac', 'N/A', ' -c:a aac'),
             ('aac', '-5', ' -c:a aac'), ('aac', '99999999999', ' -c:a aac'), ('aac', '12abc', ' -c:a aac'),
             ('mp3', '500000', ' -c:a mp3'), ('mp3', '320000', ' -c:a mp3 -ab 320000'), ('opus', '96000', ' -c:a libopus -ab 96000')]
    for codec, bit_rate, expected in cases:
        env = dict(ctx.env(), FAKE_CODEC=codec, FAKE_BIT_RATE=bit_rate)
        line = subprocess.run([str(bin_dir / 'videowmark'), 'probe', 'x.mp4'], env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=60).stdout.decode().strip()
        if line != 'x.mp4' + expected:
            raise AssertionError('%s %s: %r, expected %r' % (codec, bit_rate, line, 'x.mp4' + expected))


# -------------------------------------------------------------------------------- HLS
def hls_segments(directory):
    return sorted(p.name for p in directory.glob('out*.ts'))


class HlsFixture:
    def __init__(self, work, wav, segments):
        self.work, self.wav, self.segments = work, wav, segments
        self.source = work / 'as0'
        self.prepared = work / 'as0prep'


def build_hls(ctx, seconds, unicode_dirs=False):
    """Segments of an AAC HLS stream and the segments prepared by hls-prepare."""
    work = ctx.new_dir('hls')
    if unicode_dirs:
        work = work / 'ścieżka 音'
        work.mkdir()
    wav = work / 'input.wav'
    ctx.make_wav(wav, seconds)
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', wav, '-f', 'hls', '-c:a:0', 'aac', '-ab', '192k',
             '-master_pl_name', 'replay.m3u8', '-hls_list_size', '0', '-hls_time', '10', work / 'as%v' / 'out.m3u8'])
    segments = hls_segments(work / 'as0')
    if len(segments) < 3:
        raise AssertionError('ffmpeg produced %d segments' % len(segments))
    ctx.run([ctx.audiowmark, 'hls-prepare', work / 'as0', work / 'as0prep', 'out.m3u8', wav])
    fixture = HlsFixture(work, wav, segments)
    if hls_segments(fixture.prepared) != segments:
        raise AssertionError('hls-prepare wrote different segments')
    if (fixture.prepared / 'out.m3u8').read_bytes() != (fixture.source / 'out.m3u8').read_bytes():
        raise AssertionError('hls-prepare changed the playlist bytes')
    ctx.assert_tmp_clean()
    return fixture


def shared_hls(ctx):
    if 'hls' not in ctx.media_cache:
        ctx.media_cache['hls'] = build_hls(ctx, 70)
    return ctx.media_cache['hls']


def check_hls(ctx, seconds, unicode_dirs):
    fixture = build_hls(ctx, seconds, unicode_dirs)
    work = fixture.work
    (work / 'as0m').mkdir()
    for name in fixture.segments:
        ctx.run([ctx.audiowmark, 'hls-add', fixture.prepared / name, work / 'as0m' / name, PAYLOAD])
    shutil.copy2(fixture.source / 'out.m3u8', work / 'as0m' / 'out.m3u8')
    if sorted(p.name for p in (work / 'as0m').iterdir()) != sorted(fixture.segments + ['out.m3u8']):
        raise AssertionError('unexpected files in the watermarked HLS directory')
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', work / 'as0m' / 'out.m3u8', work / 'result.wav'])
    out = ctx.run([ctx.audiowmark, 'cmp', work / 'result.wav', PAYLOAD]).out
    match = re.search(r'match_count (\d+) (\d+)', out)
    if not match or int(match.group(1)) < max(1, seconds // 40):
        raise AssertionError('HLS watermark not detected:\n' + out[-1500:])
    ctx.assert_tmp_clean()


@test(smoke=True)
def hls_roundtrip(ctx):
    check_hls(ctx, 70, unicode_dirs=True)


@test()
def hls_roundtrip_long(ctx):
    check_hls(ctx, 200, unicode_dirs=False)


@test(smoke=True)
def hls_playlist_bytes_are_preserved(ctx):
    """CRLF line endings, comments and a missing final newline must survive hls-prepare unchanged."""
    fixture = shared_hls(ctx)
    work = ctx.new_dir('hls-playlist')
    shutil.copytree(fixture.source, work / 'as0')
    playlist = (work / 'as0' / 'out.m3u8').read_bytes().replace(b'\n', b'\r\n').rstrip(b'\r\n') + b'\r\n\r\n# trailing comment'
    (work / 'as0' / 'out.m3u8').write_bytes(playlist)
    ctx.run([ctx.audiowmark, 'hls-prepare', work / 'as0', work / 'prep', 'out.m3u8', fixture.wav])
    if (work / 'prep' / 'out.m3u8').read_bytes() != playlist:
        raise AssertionError('playlist bytes changed')
    if hls_segments(work / 'prep') != fixture.segments:
        raise AssertionError('segments differ')
    ctx.assert_tmp_clean()


@test(smoke=True)
def hls_pipes(ctx):
    """hls-add can read stdin and write stdout, and gives the same bytes as the file version."""
    fixture = shared_hls(ctx)
    work = ctx.new_dir('hls-pipes')
    name = fixture.segments[1]
    prepared = fixture.prepared / name
    reference = work / 'reference.ts'
    ctx.run([ctx.audiowmark, 'hls-add', prepared, reference, PAYLOAD])
    expected = reference.read_bytes()
    if len(expected) < 1880 or expected[0] != 0x47:
        raise AssertionError('not an MPEG-TS segment')

    # file -> stdout
    piped = ctx.run([ctx.audiowmark, 'hls-add', prepared, '-', PAYLOAD]).stdout
    if piped != expected:
        raise AssertionError('stdout output differs from the file output (%d vs %d bytes)' % (len(piped), len(expected)))
    # stdin -> stdout
    piped = ctx.run([ctx.audiowmark, 'hls-add', '-', '-', PAYLOAD], input=prepared.read_bytes()).stdout
    if piped != expected:
        raise AssertionError('stdin/stdout output differs from the file output')
    # stdin -> file
    ctx.run([ctx.audiowmark, 'hls-add', '-', work / 'from-stdin.ts', PAYLOAD], input=prepared.read_bytes())
    if (work / 'from-stdin.ts').read_bytes() != expected:
        raise AssertionError('stdin -> file output differs')
    ctx.assert_tmp_clean()


@test(smoke=True)
def hls_add_keeps_existing_output_on_failure(ctx):
    fixture = shared_hls(ctx)
    work = ctx.new_dir('hls-atomic')
    name = fixture.segments[0]
    prepared = work / 'in.ts'
    shutil.copy2(fixture.prepared / name, prepared)
    digest = hashlib.sha256(prepared.read_bytes()).hexdigest()
    out = work / 'out.ts'
    sentinel = b'previous segment'
    out.write_bytes(sentinel)

    def unchanged():
        if out.read_bytes() != sentinel:
            raise AssertionError('existing output was modified')
        if sorted(p.name for p in work.iterdir()) != ['in.ts', 'out.ts']:
            raise AssertionError('leftover files: %s' % sorted(p.name for p in work.iterdir()))
        ctx.assert_tmp_clean()

    ctx.run([ctx.audiowmark, 'hls-add', prepared, out, 'not-hex'], expect='fail')
    unchanged()
    ctx.run([ctx.audiowmark, 'hls-add', '--key', work / 'missing.key', prepared, out, PAYLOAD], expect='fail')
    unchanged()
    bad = work / 'bad-input.ts'
    bad.write_bytes(b'this is not an mpeg-ts stream' * 100)
    ctx.run([ctx.audiowmark, 'hls-add', bad, out, PAYLOAD], expect='fail')
    bad.unlink()
    unchanged()

    # input and output must be different files
    proc = ctx.run([ctx.audiowmark, 'hls-add', prepared, prepared, PAYLOAD], expect='fail')
    if 'different files' not in proc.err:
        raise AssertionError(proc.err)
    alias = work / 'alias.ts'
    try:
        os.link(prepared, alias)
    except OSError:
        alias = None
    if alias is not None:
        ctx.run([ctx.audiowmark, 'hls-add', prepared, alias, PAYLOAD], expect='fail')
        alias.unlink()
    if hashlib.sha256(prepared.read_bytes()).hexdigest() != digest:
        raise AssertionError('input segment was modified')
    unchanged()

    # success replaces the old segment
    ctx.run([ctx.audiowmark, 'hls-add', prepared, out, PAYLOAD])
    if out.read_bytes() == sentinel or sorted(p.name for p in work.iterdir()) != ['in.ts', 'out.ts']:
        raise AssertionError('segment was not replaced cleanly')
    ctx.assert_tmp_clean()


@test(smoke=True)
def hls_missing_tool_and_failing_child(ctx):
    fixture = shared_hls(ctx)
    work = ctx.new_dir('hls-tools')
    # no ffmpeg/ffprobe beside audiowmark and none on PATH
    bin_dir = ctx.new_dir('hls-no-tools-bin')
    source = pathlib.Path(ctx.bin_dir / ('audiowmark.exe' if WINDOWS else 'audiowmark'))
    try:
        os.link(source, bin_dir / source.name)
    except OSError:
        shutil.copy2(source, bin_dir / source.name)
    proc = ctx.run([bin_dir / source.name, 'hls-prepare', fixture.source, work / 'p1', 'out.m3u8', fixture.wav], expect='fail')
    if 'ffmpeg' not in proc.err:
        raise AssertionError('missing tool is not reported:\n' + proc.err)
    proc = ctx.run([bin_dir / source.name, 'hls-prepare', fixture.source, work / 'p1b', 'out.m3u8', fixture.wav], expect='fail')

    # a child that exits with an error: the audio master is not audio
    garbage = work / 'master.wav'
    garbage.write_bytes(b'not audio at all' * 100)
    proc = ctx.run([ctx.audiowmark, 'hls-prepare', fixture.source, work / 'p2', 'out.m3u8', garbage], expect='fail')
    if 'failed' not in proc.err:
        raise AssertionError(proc.err)
    # a segment ffprobe cannot read
    broken = work / 'broken'
    shutil.copytree(fixture.source, broken)
    (broken / fixture.segments[0]).write_bytes(b'\0' * 4096)
    ctx.run([ctx.audiowmark, 'hls-prepare', broken, work / 'p3', 'out.m3u8', fixture.wav], expect='fail')
    ctx.assert_tmp_clean()


@test(smoke=True)
def hls_rejects_unsafe_segment_names(ctx):
    work = ctx.new_dir('hls-unsafe')
    wav = work / 'input.wav'
    ctx.make_wav(wav, 20)
    (work / 'as0').mkdir()
    ctx.run([ctx.ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', wav, '-f', 'hls', '-c:a:0', 'aac', '-ab', '192k',
             '-hls_list_size', '0', '-hls_time', '10', work / 'as0' / 'out.m3u8'])
    playlist = (work / 'as0' / 'out.m3u8').read_text().replace('out0.ts', '../escaped.ts')
    (work / 'as0' / 'out.m3u8').write_text(playlist)
    proc = ctx.run([ctx.audiowmark, 'hls-prepare', work / 'as0', work / 'as0prep', 'out.m3u8', wav], expect='fail')
    if 'unsafe segment name' not in proc.err:
        raise AssertionError(proc.err)
    if (work / 'escaped.ts').exists() or (work / 'as0prep').exists():
        raise AssertionError('hls-prepare wrote output for an unsafe playlist')
    ctx.assert_tmp_clean()


# ------------------------------------------------------------------------------ runner
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--bin-dir', type=pathlib.Path, required=True,
                        help='directory containing audiowmark, videowmark, ffmpeg and ffprobe')
    parser.add_argument('--smoke', action='store_true', help='run the short subset')
    parser.add_argument('--keep', action='store_true', help='keep the temporary directory')
    parser.add_argument('--only', action='append', default=[], help='run tests whose name contains this text')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='backslashreplace', line_buffering=True)
        sys.stderr.reconfigure(errors='backslashreplace', line_buffering=True)

    bin_dir = args.bin_dir.resolve()
    root = pathlib.Path(tempfile.mkdtemp(prefix='audiowmark-full-test-')).resolve()
    ctx = Context(bin_dir, root)
    missing = [p for p in (ctx.audiowmark, ctx.videowmark, ctx.ffmpeg, ctx.ffprobe) if not os.path.isfile(p)]
    if missing:
        print('missing executables: ' + ', '.join(missing), file=sys.stderr)
        return 2

    failures = []
    passed = skipped = 0
    started = time.time()
    try:
        for name, function, smoke, posix_only, windows_only in TESTS:
            if args.smoke and not smoke:
                continue
            if args.only and not any(text in name for text in args.only):
                continue
            if (posix_only and WINDOWS) or (windows_only and not WINDOWS):
                print('SKIP  %s (not applicable on this OS)' % name)
                skipped += 1
                continue
            t0 = time.time()
            try:
                function(ctx)
                print('PASS  %s (%.1fs)' % (name, time.time() - t0))
                passed += 1
            except Skip as reason:
                print('SKIP  %s (%s)' % (name, reason))
                skipped += 1
            except Exception as error:   # noqa: BLE001 - report every failure and continue
                print('FAIL  %s (%.1fs)\n%s' % (name, time.time() - t0, str(error)))
                failures.append(name)
                for leftover in ctx.tmp.iterdir():      # keep later tests independent
                    shutil.rmtree(leftover, ignore_errors=True)
    finally:
        if args.keep:
            print('kept ' + str(root))
        else:
            def force(function, path, _info):
                os.chmod(path, stat.S_IWRITE)
                function(path)
            shutil.rmtree(root, onerror=force)
    print('%d passed, %d skipped, %d failed in %.0fs' % (passed, skipped, len(failures), time.time() - started))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
