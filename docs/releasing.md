# CLI and full releases

The `Release packages` workflow builds five standalone CLI archives, five
full archives, PDF and HTML documentation, corresponding sources, licenses,
and `SHA256SUMS`. It runs on pull requests,
manual dispatches, and `release: published` (including prereleases). Pull
request and manual builds only upload workflow artifacts. They never modify
a Release or publish to a package registry.

| Target suffix | CLI | Runtime requirement |
| --- | --- | --- |
| `win7-x86_64` | EXE | Windows 7 SP1 x64 or newer, MSVCRT |
| `linux-musl-x86_64` | fully static | Linux x86_64, glibc or musl |
| `linux-musl-aarch64` | fully static | Linux ARM64, glibc or musl |
| `macos-x86_64` | executable | macOS 15+ Intel |
| `macos-aarch64` | executable | macOS 15+ Apple Silicon |

Audio, resampling and cryptography dependencies are built from the pinned
sources in `scripts/release/dependencies.lock.json`. Their recursive codec
sources include Ogg, Vorbis, FLAC and Opus; MP3 decoding uses mpg123. Linux
CLIs are fully static. Windows links the C++ and GCC runtimes statically;
macOS uses Apple's system libc++ and libSystem. The `cli` variant excludes
FFmpeg, HLS and `videowmark`. Builds do not use `-march=native`.

The `full` variant adds HLS, native `videowmark`, and bundled `ffmpeg` and
`ffprobe`. It requires no Bash, Python, or separately installed multimedia
libraries at runtime. Helpers must stay beside the executable in `bin/`;
full builds use `--enable-bundled-tools` and never fall back to `PATH`.
Ordinary source builds default to sibling lookup followed by `PATH`.

Full dependencies additionally come from `dependencies-full.lock.json`:
FFmpeg 7.1.5 and LAME 3.100. FFmpeg keeps its built-in software codecs,
formats and filters, with explicit libmp3lame, libopus and libvorbis support.
Autodetection of external libraries, network protocols, capture devices,
hardware acceleration and ffplay are disabled. No external H.264/H.265
encoder or nonfree library is included. HLS handles local AAC/MPEG-TS
playlists and segments; it does not provide a streaming server.

`videowmark add` copies video and preserves AAC, MP3, Opus, Vorbis, FLAC or
PCM audio using a corresponding encoder. Unsupported audio codecs fail
without fallback. Only one audio and one video stream are accepted; other
streams are not copied. Input and output extensions must match. Existing
output is atomically replaced after successful processing, and remains
untouched on failure. Intermediate audio uses private temporary directories.

Windows builds use MSYS2 **MINGW64/MSVCRT**, with `WINVER` and `_WIN32_WINNT`
set to `0x0601`. MSYS2 provides the compiler and build tools; all audio
libraries are built from source. UCRT and prebuilt MSYS2 audio libraries are
not used. Modern Windows CI verifies imports and runs the extracted CLI
outside MSYS2, including Unicode paths and binary stdin/stdout. Actual Windows
7 SP1 execution remains a manual acceptance check: run `--version`, generate
40 seconds with `test-gen-noise`, then use `add` and `cmp` with a known payload
on Windows 7 SP1 x64 and record the OS version and results. For full packages,
also run the HLS prepare/add/decode round-trip (including binary pipes) and
`videowmark add/get`, with Unicode paths, using the bundled tools. Run the
same `tests/full-test.py --bin-dir PATH/TO/bin --smoke` acceptance harness
with a Python version compatible with that test machine, or reproduce its
commands manually. Python is a test dependency, not a package requirement.
Hosted Windows Server 2022 checks do not prove Windows 7 compatibility.
No Authenticode,
Developer ID certificate or notarization is required. macOS binaries receive
an ad hoc signature.

## Release process

1. Review and merge the implementation. Run the workflow manually first and
   download its artifacts. Confirm all ten native jobs, documentation and the complete
   asset verification pass; perform the Windows 7 manual checks.
2. Create a tag on the intended commit. Tags must be SemVer with an optional
   `v`, for example `v1.2.3` or `v1.2.3-rc.1`.
3. Create and publish the existing GitHub Release for that tag, optionally as
   a prerelease. Publication triggers an exact tag checkout. The workflow
   checks the tag resolves to the checkout commit.
4. All ten native builds, documentation and source/license packaging must succeed. The
   read-only verification job checks all fourteen assets, writes `SHA256SUMS`,
   and saves the complete `release-assets` workflow artifact on every run.
   The default token is read-only; only the final Release upload job gets
   `contents: write`. It rechecks those checksums and uploads with
   `gh release upload --clobber`. It never creates or publishes a Release.
   Rerunning updates assets with its own deterministic names and preserves
   other Release assets. There is no package registry publication.

Manual and PR versions are `0.0.0-dev.<commit>`. Manual workflow dispatch does
not accept a publication option. Downloadable workflow artifacts remain
available for the first full build before any Release exists.

## Layout and verification

Archive roots are `audiowmark-VERSION-{cli,full}-TARGET` and contain `bin/`,
man pages, README, licenses, build scripts and `metadata.json`. Full archives
contain four native programs. Metadata records the variant, target, source
commit, dependencies and FFmpeg build configuration. Every executable is
audited, and every macOS executable is signed ad hoc.

The platform-independent `audiowmark-VERSION-docs.pdf` and
`audiowmark-VERSION-docs.html` contain the existing technical manual with
version and commit identification. HTML embeds its SVG/PNG graphics and
works offline as a single file. Documentation is built once on Linux using
Pandoc, Graphviz, gnuplot, XeLaTeX, pygraphviz and pandocfilters. Build with
`VERSION=1.2.3 scripts/release/build-docs.sh`; output goes to `dist/`.
`--with-docs` checks these tools, and the build keeps generated files outside
the source tree.

Each native build runs the complete `make check` CLI regression suite, audits
OS imports, architecture and deployment versions, and then tests the actual
extracted package from an unrelated directory. Full builds include the
existing HLS and all 18 RAW format tests on every target, including macOS.
Full integration tests also cover codec preservation, unchanged video packet
data, A/V timing within 100 ms, error handling and temporary-file cleanup.
The package smoke test checks
version metadata, Unicode paths and keys, watermark add/detect with the exact
expected payload, audio layout, and binary stdin/stdout. Linux packages are
also exercised in clean Alpine and Ubuntu containers without audio libraries
or access to the builder dependency prefix. Dependency prefix caches are
separated by variant, target, compiler/image identity, source lock, recipe and patch
hashes.

The asset gate rejects missing, extra, empty or incorrectly described
packages. The exact set is five `cli` archives, five `full` archives, one
source archive, one licenses archive, and two documentation files;
`SHA256SUMS` covers all fourteen. Source and license archives contain the
union of both variants' dependencies.

Check downloaded assets before use:

```sh
sha256sum -c SHA256SUMS
```

The source archive contains the exact project commit, each locked dependency
source archive, patches, manifests and build recipes. Binary archives carry
upstream notices for the sources actually linked. The standalone licenses
archive contains their union, including GPL and GCC Runtime Library Exception
notices. Compiler executables are not redistributed.

## Reproduce a native build

Install Autoconf, Automake, Libtool, pkg-config, a C/C++ compiler, Make, CMake,
Ninja, NASM, Python 3.9+, patch, and Git. Use the matching native architecture; the
Linux entry point chooses the pinned Alpine image from
`scripts/release/images.lock.json`.

```sh
export TARGET=linux-musl-x86_64 VERSION=1.2.3 VARIANT=full
scripts/release/container-build.sh
scripts/release/container-smoke.sh
```

On macOS or in the MINGW64 shell on Windows:

```sh
export TARGET=macos-aarch64 VERSION=1.2.3 VARIANT=full
export RELEASE_WORK="$PWD/.release/$VARIANT/$TARGET"
scripts/release/build.sh
```

`VARIANT` defaults to `cli`. To unpack only one variant without collisions:

```sh
python3 scripts/release/unpack.py --artifacts dist --variant full --cli .release/unpacked-full
python3 scripts/release/smoke.py --variant full --cli ".release/unpacked-full/$TARGET/bin/audiowmark" --full-tests tests/full-test.py
```

Use the `.exe` suffix for the Windows executable. `SOURCE_CACHE` can point to the source bundle's absolute `dependencies/`
directory to avoid downloading sources again. `JOBS` defaults to four.
Build scripts copy and stamp the project version in a separate work directory,
leaving the original checkout unchanged. All compiler/linker flags are in
`environment.sh` and `build.sh`; installed dependency archives live in
`RELEASE_WORK/prefix`. Delete that directory after changing build flags unless
using the workflow's matching cache key.
