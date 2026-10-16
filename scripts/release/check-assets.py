#!/usr/bin/env python3
"""Require the complete 14-file release set, check every archive and document against the locked sources, then write SHA256SUMS."""
import argparse
import hashlib
import json
import pathlib
import re
import shlex
import sys
import tarfile
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from sources import effective_manifest, entries

CLI_TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
TOOLS = {'cli': ('audiowmark',), 'full': ('audiowmark', 'videowmark', 'ffmpeg', 'ffprobe')}
COMMIT = re.compile(r'[0-9a-f]{40}')
FFMPEG_VERSION = re.compile(r'ffmpeg version 7\.1\.5(?:\s|$)')
# Must match the options configured in build-ffmpeg.sh; the packaged binary has to report them.
FFMPEG_REQUIRED_FLAGS = ('--disable-autodetect', '--disable-network', '--disable-hwaccels', '--disable-avdevice',
                         '--disable-indevs', '--disable-outdevs', '--disable-ffplay', '--disable-doc', '--disable-debug',
                         '--disable-shared', '--enable-static', '--enable-libmp3lame', '--enable-libopus', '--enable-libvorbis')
FFMPEG_FORBIDDEN_FLAGS = ('--enable-gpl', '--enable-nonfree')
RECIPES = ('build.sh', 'build-deps.sh', 'build-ffmpeg.sh', 'environment.sh', 'sources.py',
           'dependencies.lock.json', 'dependencies-full.lock.json')

def package_name(version, variant, target):
    return f'audiowmark-{version}-{variant}-{target}' + ('.zip' if target.startswith('win7-') else '.tar.gz')

def expected_names(version):
    names = {package_name(version, variant, target) for variant in TOOLS for target in CLI_TARGETS}
    names.update((f'audiowmark-{version}-source.tar.gz', f'audiowmark-{version}-licenses.tar.gz',
                  f'audiowmark-{version}-docs.pdf', f'audiowmark-{version}-docs.html'))
    return names

class Member:
    def __init__(self, name, size, mode):
        self.name, self.size, self.mode = name, size, mode

def open_archive(path, wanted=(), digest_prefix=None):
    """One streaming pass: member listing, the bytes of the wanted members, and sha256 of members under digest_prefix."""
    members, contents, digests = [], {}, {}
    if path.name.endswith('.zip'):
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                members.append(Member(info.filename, info.file_size, None))
                if info.filename in wanted or (digest_prefix and info.filename.startswith(digest_prefix)):
                    data = z.read(info)
                    if info.filename in wanted:
                        contents[info.filename] = data
                    if digest_prefix and info.filename.startswith(digest_prefix):
                        digests[info.filename] = hashlib.sha256(data).hexdigest()
    else:
        with tarfile.open(path, 'r:gz') as tar:
            for member in tar:
                if not member.isfile():
                    continue
                members.append(Member(member.name, member.size, member.mode))
                if member.name in wanted or (digest_prefix and member.name.startswith(digest_prefix)):
                    data = tar.extractfile(member).read()
                    if member.name in wanted:
                        contents[member.name] = data
                    if digest_prefix and member.name.startswith(digest_prefix):
                        digests[member.name] = hashlib.sha256(data).hexdigest()
    return members, contents, digests

def check_members(members, root):
    """Every member must live under the package root; raw path segments may not climb out of it."""
    for member in members:
        if member.name.startswith('/') or '..' in member.name.split('/') or not (member.name == root or member.name.startswith(root + '/')):
            raise ValueError('unexpected archive member ' + member.name)

def load_json(contents, name):
    try:
        return json.loads(contents[name])
    except (KeyError, ValueError) as error:
        raise ValueError(f'{name} is missing or malformed ({error})')

def lock_copy_name(lock_filename):
    # sources.py keeps the base lock beside the effective manifest under an unambiguous name.
    return 'dependencies-base.lock.json' if lock_filename == 'dependencies.lock.json' else lock_filename

def check_locks(manifest, digests, prefix):
    for lock in manifest['locks']:
        name = prefix + lock_copy_name(lock['filename'])
        if name not in digests:
            raise ValueError('missing member ' + name)
        if digests[name] != lock['sha256']:
            raise ValueError('lock digest mismatch for ' + name)

def ffmpeg_configuration(lines):
    """Option names from FFmpeg -buildconf output.

    FFmpeg prints its configuration twice: an inline 'configuration: ...' line after -version, and a bare
    'configuration:' header followed by one indented option per line. Returns (inline, block) sets; None when absent.
    """
    inline, block, in_block = None, None, False
    for raw in lines:
        line = raw.strip()
        if line.startswith('configuration:'):
            rest = shlex.split(line[len('configuration:'):])
            in_block = not rest
            if rest:
                inline = (inline or set()) | {token.split('=', 1)[0] for token in rest if token.startswith('--')}
            else:
                block = block or set()
            continue
        if in_block:
            if line.startswith('--'):
                block.update(token.split('=', 1)[0] for token in shlex.split(line))
                continue
            in_block = False
    return inline, block

def check_ffmpeg(metadata):
    if not FFMPEG_VERSION.match(str(metadata.get('ffmpeg_version', ''))):
        raise ValueError(f"metadata ffmpeg_version is {metadata.get('ffmpeg_version')!r}, expected FFmpeg 7.1.5")
    inline, block = ffmpeg_configuration(metadata.get('ffmpeg_buildconf') or [])
    sources = [flags for flags in (inline, block) if flags]
    if not sources:
        raise ValueError('metadata ffmpeg_buildconf has no configuration')
    if inline and block and inline != block:
        raise ValueError('metadata ffmpeg_buildconf inline and per-option configurations disagree')
    flags = sources[0]
    missing = [flag for flag in FFMPEG_REQUIRED_FLAGS if flag not in flags]
    if missing:
        raise ValueError('FFmpeg build is missing required flags: ' + ' '.join(missing))
    forbidden = [flag for flag in FFMPEG_FORBIDDEN_FLAGS if flag in flags]
    if forbidden:
        raise ValueError('FFmpeg build has forbidden flags: ' + ' '.join(forbidden))

def check_package(path, version, variant, target):
    root = f'audiowmark-{version}-{variant}-{target}'
    members, contents, _ = open_archive(path, wanted={root + '/metadata.json'})
    check_members(members, root)
    names = {m.name for m in members}
    for required in (root + '/metadata.json', root + '/README.adoc', root + '/audiowmark.1', root + '/licenses/audiowmark-COPYING'):
        if required not in names:
            raise ValueError('missing member ' + required)
    if variant == 'full' and root + '/videowmark.1' not in names:
        raise ValueError('missing member ' + root + '/videowmark.1')
    windows = target.startswith('win7-')
    suffix = '.exe' if windows else ''
    bins = {m.name[len(root) + 5:]: m for m in members if m.name.startswith(root + '/bin/')}
    expected_bins = {tool + suffix for tool in TOOLS[variant]}
    if set(bins) != expected_bins:
        raise ValueError(f'bin/ contents {sorted(bins)} differ from expected {sorted(expected_bins)}')
    for name, member in bins.items():
        if member.size == 0:
            raise ValueError('empty binary: bin/' + name)
        if not windows and not member.mode & 0o111:
            raise ValueError('binary is not executable: bin/' + name)
    metadata = load_json(contents, root + '/metadata.json')
    for key, value in (('version', version), ('target', target), ('kind', variant), ('variant', variant)):
        if metadata.get(key) != value:
            raise ValueError(f'metadata {key}={metadata.get(key)!r}, expected {value!r}')
    if not COMMIT.fullmatch(str(metadata.get('commit', ''))):
        raise ValueError('metadata commit is not a full hash')
    if metadata.get('dependencies') != {'schema': 1, 'sources': entries(variant)}:
        raise ValueError(f'metadata dependencies do not match sources.entries({variant!r})')
    if variant == 'full':
        check_ffmpeg(metadata)
    return metadata['commit']

def check_source(path, version):
    root = f'audiowmark-{version}-source'
    manifest = effective_manifest('full')
    members, contents, digests = open_archive(
        path, wanted={root + '/metadata.json', root + '/audiowmark/release-metadata.json', root + '/dependencies/dependencies.lock.json'},
        digest_prefix=root + '/dependencies/')
    check_members(members, root)
    names = {m.name for m in members}
    for required in (root + '/metadata.json', root + '/COPYING', root + '/audiowmark/release-metadata.json',
                     root + '/audiowmark/docs/audiowmark.md', root + '/audiowmark/docs/graphviz.py',
                     root + '/dependencies/dependencies.lock.json'):
        if required not in names:
            raise ValueError('missing member ' + required)
    for recipe in RECIPES:
        if root + '/build-scripts/' + recipe not in names:
            raise ValueError('missing build recipe ' + root + '/build-scripts/' + recipe)
    if not any(n.startswith(root + '/build-scripts/patches/') and n.endswith('.patch') for n in names):
        raise ValueError('missing build patches under ' + root + '/build-scripts/patches/')
    metadata = load_json(contents, root + '/metadata.json')
    release = load_json(contents, root + '/audiowmark/release-metadata.json')
    if metadata.get('version') != version or release.get('version') != version:
        raise ValueError('source metadata version does not match ' + version)
    if metadata.get('commit') != release.get('commit') or not COMMIT.fullmatch(str(metadata.get('commit', ''))):
        raise ValueError('source metadata commit is inconsistent')
    if metadata.get('dependencies') != manifest:
        raise ValueError('source metadata dependencies do not match the effective full manifest')
    if load_json(contents, root + '/dependencies/dependencies.lock.json') != manifest:
        raise ValueError('dependencies/dependencies.lock.json does not match the effective full manifest')
    check_locks(manifest, digests, root + '/dependencies/')
    for entry in entries('full'):
        name = f"{root}/dependencies/{entry['filename']}"
        if name not in digests:
            raise ValueError('missing member ' + name)
        if digests[name] != entry['sha256']:
            raise ValueError('SHA256 mismatch for ' + name)
    return metadata['commit']

def check_licenses(path, version):
    # The notices archive has no metadata.json by design; its name carries the version, the manifest carries the locks.
    root = f'audiowmark-{version}-licenses'
    manifest = effective_manifest('full')
    members, contents, digests = open_archive(path, wanted={root + '/dependencies.lock.json'}, digest_prefix=root + '/')
    check_members(members, root)
    names = {m.name for m in members}
    for required in (root + '/audiowmark-COPYING', root + '/toolchain/GCC-COPYING.RUNTIME', root + '/dependencies.lock.json'):
        if required not in names:
            raise ValueError('missing member ' + required)
    if load_json(contents, root + '/dependencies.lock.json') != manifest:
        raise ValueError('licenses dependencies.lock.json does not match the effective full manifest')
    check_locks(manifest, digests, root + '/')
    for entry in entries('full'):
        if not any(n.startswith(f"{root}/{entry['name']}/") for n in names):
            raise ValueError('no license notices for ' + entry['name'])

def check_pdf(path):
    data = path.read_bytes()
    if not data.startswith(b'%PDF-') or b'%%EOF' not in data[-2048:]:
        raise ValueError('not a complete PDF document')

def check_html(path, version, commit):
    try:
        text = path.read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('HTML is not valid UTF-8')
    if '<html' not in text or '</html>' not in text:
        raise ValueError('HTML document is incomplete')
    if f'<title>audiowmark {version}</title>' not in text:
        raise ValueError('HTML title does not carry version ' + version)
    if f'commit {commit[:12]}' not in text:
        raise ValueError('HTML does not carry source commit ' + commit[:12])

def validate(directory, version):
    expected = expected_names(version)
    actual = {p.name for p in directory.iterdir() if p.is_file() and p.name != 'SHA256SUMS'}
    problems = []
    if actual != expected:
        problems.append('release asset mismatch: missing=' + str(sorted(expected - actual)) + ' extra=' + str(sorted(actual - expected)))
    for name in sorted(expected & actual):
        if (directory / name).stat().st_size == 0:
            problems.append('empty asset ' + name)
    commits = {}
    checks = [(package_name(version, variant, target), lambda p, v=variant, t=target: check_package(p, version, v, t))
              for variant in TOOLS for target in CLI_TARGETS]
    checks.append((f'audiowmark-{version}-source.tar.gz', lambda p: check_source(p, version)))
    checks.append((f'audiowmark-{version}-licenses.tar.gz', lambda p: check_licenses(p, version)))
    for name, check in checks:
        path = directory / name
        if name in actual and path.stat().st_size:
            try:
                commit = check(path)
                if commit is not None:
                    commits[name] = commit
            except (ValueError, tarfile.TarError, zipfile.BadZipFile, KeyError) as error:
                problems.append(f'{name}: {error}')
    if len(set(commits.values())) > 1:
        problems.append('archives come from different commits: ' + str(sorted(set(commits.values()))))
    commit = next(iter(commits.values()), None)
    pdf = directory / f'audiowmark-{version}-docs.pdf'
    html = directory / f'audiowmark-{version}-docs.html'
    if pdf.name in actual and pdf.stat().st_size:
        try:
            check_pdf(pdf)
        except ValueError as error:
            problems.append(f'{pdf.name}: {error}')
    if html.name in actual and html.stat().st_size and commit:
        try:
            check_html(html, version, commit)
        except ValueError as error:
            problems.append(f'{html.name}: {error}')
    return expected, problems

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--directory', type=pathlib.Path, required=True)
    args = parser.parse_args()
    expected, problems = validate(args.directory, args.version)
    if problems:
        for problem in problems:
            print('error: ' + problem, file=sys.stderr)
        sys.exit(1)
    lines = []
    for name in sorted(expected):
        lines.append(hashlib.sha256((args.directory / name).read_bytes()).hexdigest() + '  ' + name + '\n')
    (args.directory / 'SHA256SUMS').write_text(''.join(lines))
    print(f'verified {len(expected)} release assets; wrote SHA256SUMS')

if __name__ == '__main__':
    main()
