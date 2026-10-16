#!/usr/bin/env python3
"""Positive and negative tests for the release asset gate (check-assets.py) and archive selection (unpack.py).

The gate runs in-process against a fake locked source set, because the real FFmpeg/LAME archives are not
available to unit tests. The real lock is exercised by the release workflow, which checks real archives.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
CHECK = HERE / 'check-assets.py'
UNPACK = HERE / 'unpack.py'
CLI_TARGETS = ('win7-x86_64', 'linux-musl-x86_64', 'linux-musl-aarch64', 'macos-x86_64', 'macos-aarch64')
TOOLS = {'cli': ('audiowmark',), 'full': ('audiowmark', 'videowmark', 'ffmpeg', 'ffprobe')}
VERSION = '1.2.3-test.1'
COMMIT = '0123456789abcdef0123456789abcdef01234567'
# Literal copy of the configure options in build-ffmpeg.sh, independent of the gate's constant.
FFMPEG_FLAGS = ('--disable-autodetect --disable-network --disable-hwaccels --disable-avdevice --disable-indevs '
                '--disable-outdevs --disable-ffplay --disable-doc --disable-debug --disable-shared --enable-static '
                '--enable-libmp3lame --enable-libopus --enable-libvorbis --enable-ffmpeg --enable-ffprobe')

REAL_BUILDCONF_FILE = HERE / 'testdata' / 'ffmpeg-7.1.5-buildconf.json'
REAL_BUILDCONF = json.loads(REAL_BUILDCONF_FILE.read_text())['ffmpeg_buildconf']  # captured from a real package
REAL_VERSION = 'ffmpeg version 7.1.5 Copyright (c) 2000-2026 the FFmpeg developers'

def load_checks():
    spec = importlib.util.spec_from_file_location('check_assets', CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

checks = load_checks()

# ---------------------------------------------------------------- fake locked sources
ARCHIVES = {'zita-resampler': ('zita-resampler-1.11.2.tar.gz', b'zita archive'),
            'lame': ('lame-3.100.tar.gz', b'lame archive'),
            'ffmpeg': ('ffmpeg-7.1.5.tar.xz', b'ffmpeg archive')}
BASE_NAMES = ('zita-resampler',)
FULL_NAMES = ('zita-resampler', 'lame', 'ffmpeg')

def fake_entry(name):
    filename, data = ARCHIVES[name]
    return dict(name=name, version='x', url='https://example.invalid/' + filename, filename=filename,
                sha256=hashlib.sha256(data).hexdigest())

def fake_entries(variant='cli'):
    return [fake_entry(name) for name in (FULL_NAMES if variant == 'full' else BASE_NAMES)]

BASE_LOCK = json.dumps({'schema': 1, 'sources': [fake_entry('zita-resampler')]}, indent=2).encode()
FULL_LOCK = json.dumps({'schema': 1, 'sources': [fake_entry('lame'), fake_entry('ffmpeg')]}, indent=2).encode()

def fake_manifest(variant='cli'):
    locks = [{'filename': 'dependencies.lock.json', 'sha256': hashlib.sha256(BASE_LOCK).hexdigest()}]
    if variant == 'full':
        locks.append({'filename': 'dependencies-full.lock.json', 'sha256': hashlib.sha256(FULL_LOCK).hexdigest()})
    return {'schema': 1, 'variant': variant, 'locks': locks, 'sources': fake_entries(variant)}

# ---------------------------------------------------------------- archives
def package_name(variant, target, version=VERSION):
    return f'audiowmark-{version}-{variant}-{target}' + ('.zip' if target.startswith('win7-') else '.tar.gz')

def expected_names(version=VERSION):
    names = [package_name(variant, target, version) for variant in TOOLS for target in CLI_TARGETS]
    return names + [f'audiowmark-{version}-source.tar.gz', f'audiowmark-{version}-licenses.tar.gz',
                    f'audiowmark-{version}-docs.pdf', f'audiowmark-{version}-docs.html']

def write_archive(path, members):
    """members: (name, bytes, mode). Zip members carry the mode in external_attr like Info-ZIP does."""
    if path.name.endswith('.zip'):
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data, mode in members:
                info = zipfile.ZipInfo(name)
                info.external_attr = (mode & 0xFFFF) << 16
                archive.writestr(info, data)
    else:
        with tarfile.open(path, 'w:gz') as archive:
            for name, data, mode in members:
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = mode
                archive.addfile(info, io.BytesIO(data))

def mutate(members, name, data=None, mode=None, drop=False):
    result = []
    found = False
    for member_name, member_data, member_mode in members:
        if member_name == name:
            found = True
            if drop:
                continue
            member_data = member_data if data is None else data
            member_mode = member_mode if mode is None else mode
        result.append((member_name, member_data, member_mode))
    if not found:
        raise AssertionError('fixture has no member ' + name)
    return result

def package_members(variant, target, version=VERSION, commit=COMMIT, metadata=None,
                    bin_data=None, bin_modes=None, omit_bins=(), extra_bins=None):
    root = f'audiowmark-{version}-{variant}-{target}'
    suffix = '.exe' if target.startswith('win7-') else ''
    meta = dict(version=version, target=target, kind=variant, variant=variant, commit=commit,
                dependencies=dict(schema=1, sources=fake_entries(variant)))
    if variant == 'full':
        meta.update(ffmpeg_version=REAL_VERSION, ffmpeg_buildconf=list(REAL_BUILDCONF))
    meta.update(metadata or {})
    members = [(root + '/metadata.json', json.dumps(meta).encode(), 0o644),
               (root + '/README.adoc', b'readme', 0o644),
               (root + '/audiowmark.1', b'.TH audiowmark', 0o644),
               (root + '/licenses/audiowmark-COPYING', b'GPL', 0o644)]
    if variant == 'full':
        members.append((root + '/videowmark.1', b'.TH videowmark', 0o644))
    for tool in TOOLS[variant]:
        name = tool + suffix
        if name in omit_bins:
            continue
        members.append((root + '/bin/' + name, (bin_data or {}).get(name, b'BINARY ' + name.encode()),
                        (bin_modes or {}).get(name, 0o755)))
    for name, data in (extra_bins or {}).items():
        members.append((root + '/bin/' + name, data, 0o755))
    return members

RECIPE_NAMES = ('build.sh', 'build-deps.sh', 'build-ffmpeg.sh', 'environment.sh', 'sources.py',
                'dependencies.lock.json', 'dependencies-full.lock.json')

def source_members(version=VERSION, commit=COMMIT, metadata=None):
    root = f'audiowmark-{version}-source'
    manifest = json.dumps(fake_manifest('full'), indent=2).encode()
    meta = dict(version=version, commit=commit, dependencies=fake_manifest('full'))
    meta.update(metadata or {})
    members = [(root + '/metadata.json', json.dumps(meta).encode(), 0o644),
               (root + '/COPYING', b'GPL', 0o644),
               (root + '/BUILDING.txt', b'build notes', 0o644),
               (root + '/audiowmark/release-metadata.json', json.dumps(dict(version=version, commit=commit)).encode(), 0o644),
               (root + '/audiowmark/docs/audiowmark.md', b'# Audio Watermarking', 0o644),
               (root + '/audiowmark/docs/graphviz.py', b'#!/usr/bin/env python3', 0o755),
               (root + '/dependencies/dependencies.lock.json', manifest, 0o644),
               (root + '/dependencies/dependencies-base.lock.json', BASE_LOCK, 0o644),
               (root + '/dependencies/dependencies-full.lock.json', FULL_LOCK, 0o644)]
    for name in FULL_NAMES:
        filename, data = ARCHIVES[name]
        members.append((root + '/dependencies/' + filename, data, 0o644))
    for recipe in RECIPE_NAMES:
        members.append((root + '/build-scripts/' + recipe, b'recipe ' + recipe.encode(), 0o644))
    members.append((root + '/build-scripts/patches/zita-static.patch', b'--- a\n+++ b\n', 0o644))
    return members

def licenses_members(version=VERSION, manifest=None):
    root = f'audiowmark-{version}-licenses'
    manifest_bytes = json.dumps(manifest or fake_manifest('full'), indent=2).encode()
    members = [(root + '/audiowmark-COPYING', b'GPL', 0o644),
               (root + '/toolchain/GCC-COPYING.RUNTIME', b'RUNTIME', 0o644),
               (root + '/dependencies.lock.json', manifest_bytes, 0o644),
               (root + '/dependencies-base.lock.json', BASE_LOCK, 0o644),
               (root + '/dependencies-full.lock.json', FULL_LOCK, 0o644)]
    for name in FULL_NAMES:
        members.append((f'{root}/{name}/COPYING', b'notice ' + name.encode(), 0o644))
    return members

def pdf_bytes():
    return b'%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n'

def html_text(version=VERSION, commit=COMMIT):
    return ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8" />\n'
            f'<title>audiowmark {version}</title>\n</head>\n<body>\n'
            f'<p>Technical documentation, commit {commit[:12]}</p>\n</body>\n</html>\n')

def make_release(directory, version=VERSION, commit=COMMIT):
    """Write the complete, valid 14-file release set."""
    for variant in TOOLS:
        for target in CLI_TARGETS:
            write_archive(directory / package_name(variant, target, version),
                          package_members(variant, target, version, commit))
    write_archive(directory / f'audiowmark-{version}-source.tar.gz', source_members(version, commit))
    write_archive(directory / f'audiowmark-{version}-licenses.tar.gz', licenses_members(version))
    (directory / f'audiowmark-{version}-docs.pdf').write_bytes(pdf_bytes())
    (directory / f'audiowmark-{version}-docs.html').write_text(html_text(version, commit), encoding='utf-8')

# ---------------------------------------------------------------- gate tests
class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory(prefix='audiowmark-gate-')
        self.directory = pathlib.Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        patcher = mock.patch.multiple(checks, entries=fake_entries, effective_manifest=fake_manifest)
        patcher.start()
        self.addCleanup(patcher.stop)

    def gate(self, version=VERSION):
        out, err = io.StringIO(), io.StringIO()
        argv = sys.argv
        sys.argv = ['check-assets.py', '--version', version, '--directory', str(self.directory)]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    checks.main()
                    code = 0
                except SystemExit as exit_:
                    code = exit_.code
        finally:
            sys.argv = argv
        return code, err.getvalue()

    def assertRejected(self, result, *fragments):
        code, stderr = result
        self.assertNotEqual(code, 0, 'gate accepted a broken release set')
        for fragment in fragments:
            self.assertIn(fragment, stderr)

    def replace_package(self, variant, target, members):
        write_archive(self.directory / package_name(variant, target), members)

    def replace_source(self, members):
        write_archive(self.directory / f'audiowmark-{VERSION}-source.tar.gz', members)

    def replace_licenses(self, members):
        write_archive(self.directory / f'audiowmark-{VERSION}-licenses.tar.gz', members)

    # --- complete set
    def test_complete_release_set_passes_and_writes_matching_sha256sums(self):
        make_release(self.directory)
        code, stderr = self.gate()
        self.assertEqual(code, 0, stderr)
        lines = (self.directory / 'SHA256SUMS').read_text().splitlines()
        self.assertEqual(len(lines), 14)
        for line in lines:
            digest, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256((self.directory / name).read_bytes()).hexdigest(), digest)

    def test_stale_sha256sums_is_replaced(self):
        make_release(self.directory)
        (self.directory / 'SHA256SUMS').write_text('0' * 64 + '  stale.tar.gz\n')
        self.assertEqual(self.gate()[0], 0)
        names = [line.split('  ', 1)[1] for line in (self.directory / 'SHA256SUMS').read_text().splitlines()]
        self.assertEqual(sorted(names), sorted(expected_names()))

    # --- asset set
    def test_each_missing_asset_is_rejected(self):
        for name in expected_names():
            with self.subTest(missing=name):
                make_release(self.directory)
                (self.directory / name).unlink()
                self.assertRejected(self.gate(), 'missing=', name)

    def test_extra_asset_is_rejected(self):
        make_release(self.directory)
        (self.directory / f'audiowmark-{VERSION}-cli-rogue.tar.gz').write_bytes(b'x')
        self.assertRejected(self.gate(), 'extra=')

    def test_empty_assets_are_rejected(self):
        for name in (package_name('cli', 'linux-musl-x86_64'), package_name('full', 'macos-aarch64'),
                     f'audiowmark-{VERSION}-source.tar.gz', f'audiowmark-{VERSION}-docs.pdf', f'audiowmark-{VERSION}-docs.html'):
            with self.subTest(empty=name):
                make_release(self.directory)
                (self.directory / name).write_bytes(b'')
                self.assertRejected(self.gate(), 'empty asset ' + name)

    # --- package contents
    def test_empty_binary_inside_package_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'linux-musl-x86_64', package_members('full', 'linux-musl-x86_64', bin_data={'ffmpeg': b''}))
        self.assertRejected(self.gate(), 'empty binary: bin/ffmpeg')

    def test_full_package_missing_tool_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'linux-musl-aarch64', package_members('full', 'linux-musl-aarch64', omit_bins=('ffprobe',)))
        self.assertRejected(self.gate(), 'bin/ contents')

    def test_extra_binary_is_rejected(self):
        make_release(self.directory)
        self.replace_package('cli', 'macos-x86_64', package_members('cli', 'macos-x86_64', extra_bins={'rogue': b'x'}))
        self.assertRejected(self.gate(), 'bin/ contents')

    def test_non_executable_binary_is_rejected(self):
        make_release(self.directory)
        self.replace_package('cli', 'linux-musl-x86_64', package_members('cli', 'linux-musl-x86_64', bin_modes={'audiowmark': 0o644}))
        self.assertRejected(self.gate(), 'binary is not executable: bin/audiowmark')

    def test_windows_zip_missing_exe_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'win7-x86_64', package_members('full', 'win7-x86_64', omit_bins=('ffmpeg.exe',)))
        self.assertRejected(self.gate(), 'bin/ contents')

    def test_package_path_traversal_is_rejected(self):
        make_release(self.directory)
        members = package_members('cli', 'linux-musl-x86_64')
        members.append((f'audiowmark-{VERSION}-cli-linux-musl-x86_64/../../escape', b'x', 0o644))
        self.replace_package('cli', 'linux-musl-x86_64', members)
        self.assertRejected(self.gate(), 'unexpected archive member')

    def test_missing_license_notice_in_package_is_rejected(self):
        make_release(self.directory)
        members = [m for m in package_members('cli', 'linux-musl-x86_64') if not m[0].endswith('audiowmark-COPYING')]
        self.replace_package('cli', 'linux-musl-x86_64', members)
        self.assertRejected(self.gate(), 'missing member')

    # --- package metadata
    def test_metadata_version_mismatch_is_rejected(self):
        make_release(self.directory)
        self.replace_package('cli', 'linux-musl-x86_64', package_members('cli', 'linux-musl-x86_64', metadata={'version': '9.9.9'}))
        self.assertRejected(self.gate(), "metadata version='9.9.9'")

    def test_metadata_target_mismatch_is_rejected(self):
        make_release(self.directory)
        self.replace_package('cli', 'linux-musl-x86_64', package_members('cli', 'linux-musl-x86_64', metadata={'target': 'macos-aarch64'}))
        self.assertRejected(self.gate(), "metadata target='macos-aarch64'")

    def test_variant_mismatch_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'macos-x86_64', package_members('full', 'macos-x86_64', metadata={'kind': 'cli', 'variant': 'cli'}))
        self.assertRejected(self.gate(), "metadata kind='cli'")

    def test_malformed_metadata_is_rejected(self):
        make_release(self.directory)
        members = [(name, b'{not json' if name.endswith('/metadata.json') else data, mode)
                   for name, data, mode in package_members('cli', 'linux-musl-x86_64')]
        self.replace_package('cli', 'linux-musl-x86_64', members)
        self.assertRejected(self.gate(), 'metadata.json is missing or malformed')

    def test_short_commit_is_rejected(self):
        make_release(self.directory)
        self.replace_package('cli', 'linux-musl-x86_64', package_members('cli', 'linux-musl-x86_64', commit='abc123'))
        self.assertRejected(self.gate(), 'metadata commit is not a full hash')

    def test_packages_from_different_commits_are_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'linux-musl-x86_64', package_members('full', 'linux-musl-x86_64', commit='f' * 40))
        self.assertRejected(self.gate(), 'archives come from different commits')

    # --- misdescribed dependencies and FFmpeg (block and inline forms of -buildconf)
    def test_package_dependencies_not_matching_locked_sources_are_rejected(self):
        make_release(self.directory)
        cases = {
            'empty sources': dict(schema=1, sources=[]),
            'changed sha256': dict(schema=1, sources=[dict(fake_entry('zita-resampler'), sha256='0' * 64)]),
            'extra source': dict(schema=1, sources=fake_entries('full') + [dict(fake_entry('lame'), name='rogue')]),
        }
        for label, dependencies in cases.items():
            with self.subTest(case=label):
                self.replace_package('full', 'linux-musl-x86_64',
                                     package_members('full', 'linux-musl-x86_64', metadata={'dependencies': dependencies}))
                self.assertRejected(self.gate(), 'metadata dependencies do not match sources.entries')

    def test_ffmpeg_version_other_than_7_1_5_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'linux-musl-x86_64', package_members(
            'full', 'linux-musl-x86_64', metadata={'ffmpeg_version': 'ffmpeg version 7.1.4 Copyright'}))
        self.assertRejected(self.gate(), 'expected FFmpeg 7.1.5')

    def test_real_captured_buildconf_passes_the_check(self):
        checks.check_ffmpeg({'ffmpeg_version': REAL_VERSION, 'ffmpeg_buildconf': REAL_BUILDCONF})

    def test_inline_only_buildconf_passes_the_check(self):
        checks.check_ffmpeg({'ffmpeg_version': REAL_VERSION, 'ffmpeg_buildconf': ['configuration: ' + FFMPEG_FLAGS]})

    def test_ffmpeg_build_without_required_flag_is_rejected(self):
        make_release(self.directory)
        flags = FFMPEG_FLAGS.replace(' --enable-libopus', '')
        self.replace_package('full', 'linux-musl-x86_64', package_members(
            'full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': ['configuration: ' + flags]}))
        self.assertRejected(self.gate(), 'missing required flags: --enable-libopus')

    def test_real_buildconf_missing_required_flag_in_both_forms_is_rejected(self):
        make_release(self.directory)
        lines = [line for line in REAL_BUILDCONF if line.strip() != '--enable-libopus']
        lines = [line.replace(' --enable-libopus', '') for line in lines]
        self.replace_package('full', 'linux-musl-x86_64', package_members('full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': lines}))
        self.assertRejected(self.gate(), 'missing required flags: --enable-libopus')

    def test_real_buildconf_with_inline_and_block_disagreeing_is_rejected(self):
        make_release(self.directory)
        lines = [line for line in REAL_BUILDCONF if line.strip() != '--enable-libopus']
        self.replace_package('full', 'linux-musl-x86_64', package_members('full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': lines}))
        self.assertRejected(self.gate(), 'inline and per-option configurations disagree')

    def test_forbidden_flag_in_per_option_block_is_rejected(self):
        make_release(self.directory)
        lines = list(REAL_BUILDCONF) + ['    --enable-nonfree']
        self.replace_package('full', 'linux-musl-x86_64', package_members('full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': lines}))
        self.assertRejected(self.gate(), 'inline and per-option configurations disagree')

    def test_forbidden_flag_in_both_forms_is_rejected(self):
        make_release(self.directory)
        lines = []
        for line in REAL_BUILDCONF:
            lines.append(line.replace(' --enable-libopus', ' --enable-libopus --enable-nonfree'))
            if line.strip() == '--enable-libopus':
                lines.append('    --enable-nonfree')
        self.replace_package('full', 'linux-musl-x86_64', package_members('full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': lines}))
        self.assertRejected(self.gate(), 'forbidden flags: --enable-nonfree')

    def test_ffmpeg_build_with_forbidden_flag_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'linux-musl-x86_64', package_members(
            'full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': ['configuration: ' + FFMPEG_FLAGS + ' --enable-nonfree']}))
        self.assertRejected(self.gate(), 'forbidden flags: --enable-nonfree')

    def test_ffmpeg_buildconf_without_configuration_line_is_rejected(self):
        make_release(self.directory)
        self.replace_package('full', 'linux-musl-x86_64', package_members(
            'full', 'linux-musl-x86_64', metadata={'ffmpeg_buildconf': ['libavutil 59.8.100']}))
        self.assertRejected(self.gate(), 'ffmpeg_buildconf has no configuration')

    # --- source bundle: manifest, archives, locks, recipes
    def test_source_dependency_archive_missing_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-source/dependencies/{ARCHIVES["lame"][0]}'
        self.replace_source(mutate(source_members(), name, drop=True))
        self.assertRejected(self.gate(), 'missing member ' + name)

    def test_source_dependency_archive_with_wrong_bytes_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-source/dependencies/{ARCHIVES["ffmpeg"][0]}'
        self.replace_source(mutate(source_members(), name, data=b'tampered'))
        self.assertRejected(self.gate(), 'SHA256 mismatch for ' + name)

    def test_source_manifest_not_matching_effective_manifest_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-source/dependencies/dependencies.lock.json'
        self.replace_source(mutate(source_members(), name, data=json.dumps(dict(fake_manifest('full'), sources=[])).encode()))
        self.assertRejected(self.gate(), 'dependencies/dependencies.lock.json does not match the effective full manifest')

    def test_source_lock_copy_changed_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-source/dependencies/dependencies-full.lock.json'
        self.replace_source(mutate(source_members(), name, data=FULL_LOCK + b'\n'))
        self.assertRejected(self.gate(), 'lock digest mismatch for ' + name)

    def test_source_metadata_dependencies_not_matching_is_rejected(self):
        make_release(self.directory)
        self.replace_source(source_members(metadata={'dependencies': {'schema': 1, 'sources': []}}))
        self.assertRejected(self.gate(), 'source metadata dependencies do not match the effective full manifest')

    def test_source_build_recipe_missing_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-source/build-scripts/build-ffmpeg.sh'
        self.replace_source(mutate(source_members(), name, drop=True))
        self.assertRejected(self.gate(), 'missing build recipe ' + name)

    def test_source_build_patches_missing_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-source/build-scripts/patches/zita-static.patch'
        self.replace_source(mutate(source_members(), name, drop=True))
        self.assertRejected(self.gate(), 'missing build patches')

    # --- licenses union
    def test_licenses_without_notices_for_a_dependency_are_rejected(self):
        make_release(self.directory)
        self.replace_licenses([m for m in licenses_members() if not m[0].startswith(f'audiowmark-{VERSION}-licenses/ffmpeg/')])
        self.assertRejected(self.gate(), 'no license notices for ffmpeg')

    def test_licenses_manifest_not_matching_effective_manifest_is_rejected(self):
        make_release(self.directory)
        self.replace_licenses(licenses_members(manifest=dict(fake_manifest('full'), sources=[])))
        self.assertRejected(self.gate(), 'licenses dependencies.lock.json does not match the effective full manifest')

    def test_licenses_lock_copy_missing_is_rejected(self):
        make_release(self.directory)
        name = f'audiowmark-{VERSION}-licenses/dependencies-base.lock.json'
        self.replace_licenses(mutate(licenses_members(), name, drop=True))
        self.assertRejected(self.gate(), 'missing member ' + name)

    # --- documents
    def test_truncated_pdf_is_rejected(self):
        make_release(self.directory)
        (self.directory / f'audiowmark-{VERSION}-docs.pdf').write_bytes(b'%PDF-1.7\n truncated')
        self.assertRejected(self.gate(), 'not a complete PDF document')

    def test_html_with_wrong_commit_is_rejected(self):
        make_release(self.directory)
        (self.directory / f'audiowmark-{VERSION}-docs.html').write_text(html_text(commit='f' * 40), encoding='utf-8')
        self.assertRejected(self.gate(), 'HTML does not carry source commit')

    def test_html_with_wrong_version_is_rejected(self):
        make_release(self.directory)
        (self.directory / f'audiowmark-{VERSION}-docs.html').write_text(html_text(version='0.0.1'), encoding='utf-8')
        self.assertRejected(self.gate(), 'HTML title does not carry version')

# ---------------------------------------------------------------- unpack tests
class UnpackTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory(prefix='audiowmark-unpack-')
        self.base = pathlib.Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)
        self.artifacts = self.base / 'dist'
        self.artifacts.mkdir()
        make_release(self.artifacts)

    def unpack(self, root, variant, artifacts=None):
        return subprocess.run([sys.executable, str(UNPACK), '--artifacts', str(artifacts or self.artifacts),
                               '--cli', str(root), '--variant', variant], capture_output=True, text=True)

    @staticmethod
    def bins(target_dir):
        return sorted(p.name for p in (target_dir / 'bin').iterdir())

    def test_variant_selects_only_its_archives(self):
        cli, full = self.base / 'unpacked-cli', self.base / 'unpacked-full'
        for root, variant in ((cli, 'cli'), (full, 'full')):
            result = self.unpack(root, variant)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in cli.iterdir()), sorted(CLI_TARGETS))
        self.assertEqual(sorted(p.name for p in full.iterdir()), sorted(CLI_TARGETS))
        for target in CLI_TARGETS:
            suffix = '.exe' if target.startswith('win7-') else ''
            self.assertEqual(self.bins(cli / target), ['audiowmark' + suffix])
            self.assertEqual(self.bins(full / target), sorted(t + suffix for t in TOOLS['full']))

    def test_variants_extracted_side_by_side_do_not_collide(self):
        cli, full = self.base / 'unpacked-cli', self.base / 'unpacked-full'
        self.unpack(cli, 'cli')
        self.unpack(full, 'full')
        self.assertFalse((cli / 'linux-musl-x86_64' / 'bin' / 'ffmpeg').exists())
        self.assertTrue((full / 'linux-musl-x86_64' / 'bin' / 'ffmpeg').exists())

    def test_duplicate_archive_for_same_variant_and_target_is_rejected(self):
        write_archive(self.artifacts / 'audiowmark-OTHER-cli-linux-musl-x86_64.tar.gz',
                      package_members('cli', 'linux-musl-x86_64', version='OTHER'))
        result = self.unpack(self.base / 'root', 'cli')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('duplicate cli archive for linux-musl-x86_64', result.stderr)

    def test_missing_variant_is_rejected(self):
        only_cli = self.base / 'only-cli'
        only_cli.mkdir()
        for name in expected_names():
            if '-cli-' in name:
                (only_cli / name).write_bytes((self.artifacts / name).read_bytes())
        result = self.unpack(self.base / 'root', 'full', artifacts=only_cli)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('no full archives', result.stderr)

    def test_unsafe_member_in_package_is_rejected(self):
        members = package_members('cli', 'linux-musl-x86_64')
        members.append((f'audiowmark-{VERSION}-cli-linux-musl-x86_64/../../escape', b'x', 0o644))
        write_archive(self.artifacts / package_name('cli', 'linux-musl-x86_64'), members)
        result = self.unpack(self.base / 'root', 'cli')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsafe archive member', result.stderr)

    def test_package_root_must_match_archive_name(self):
        write_archive(self.artifacts / package_name('cli', 'linux-musl-x86_64'),
                      [(name.replace('cli-linux', 'cli-renamed'), data, mode)
                       for name, data, mode in package_members('cli', 'linux-musl-x86_64')])
        result = self.unpack(self.base / 'root', 'cli')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match', result.stderr)

if __name__ == '__main__':
    unittest.main(verbosity=2)
