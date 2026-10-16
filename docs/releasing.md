# Portable CLI releases

The `Portable release packages` workflow builds five standalone CLI archives,
corresponding sources, licenses, and `SHA256SUMS` (seven archives total). It
runs on pull requests, manual dispatches, and `release: published` (including
prereleases). Pull request and manual builds only upload workflow artifacts.
They never modify a Release or publish to a package registry.

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
macOS uses Apple's system libc++ and libSystem. Packages exclude FFmpeg, HLS
and `videowmark`. Builds do not use `-march=native`.

Windows builds use MSYS2 **MINGW64/MSVCRT**, with `WINVER` and `_WIN32_WINNT`
set to `0x0601`. MSYS2 provides the compiler and build tools; all audio
libraries are built from source. UCRT and prebuilt MSYS2 audio libraries are
not used. Modern Windows CI verifies imports and runs the extracted CLI
outside MSYS2, including Unicode paths and binary stdin/stdout. Actual Windows
7 SP1 execution remains a manual acceptance check: run `--version`, generate
40 seconds with `test-gen-noise`, then use `add` and `cmp` with a known payload
on Windows 7 SP1 x64 and record the OS version and results. No Authenticode,
Developer ID certificate or notarization is required. macOS binaries receive
an ad hoc signature.

## Release process

1. Review and merge the implementation. Run the workflow manually first and
   download its artifacts. Confirm all five native jobs and the complete
   asset verification pass; perform the Windows 7 manual checks.
2. Create a tag on the intended commit. Tags must be SemVer with an optional
   `v`, for example `v1.2.3` or `v1.2.3-rc.1`.
3. Create and publish the existing GitHub Release for that tag, optionally as
   a prerelease. Publication triggers an exact tag checkout. The workflow
   checks the tag resolves to the checkout commit.
4. All five native builds and source/license packaging must succeed. The
   read-only verification job checks all seven archives, writes `SHA256SUMS`,
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

Archive roots are `audiowmark-VERSION-cli-TARGET` and contain `bin/`, the manual,
README, licenses, build scripts and `metadata.json`. The CLI has no runtime
dependency on separately distributed audiowmark libraries.

Each native build runs the complete `make check` CLI regression suite, audits
native binary OS imports, architecture, and runtime/deployment versions, and
checks WAV audio layout. The WAV test is a single `add`/`get` round trip; the
unconditional RAW round trip uses two `add` calls with two keys and two
payloads. The format tests
use the real prerecorded synthetic `marked.flac`, `marked.mp3`, `marked.ogg`
(Vorbis), and `marked.opus` fixtures for decoding; they need neither FFmpeg
nor Python.

The package smoke test extracts the package and executes its CLI from an
unrelated temporary working directory. It checks version metadata, Unicode
paths and key names, direct `get`, and both JSON output modes by fully parsing
the results and checking the exact payload and key. It also checks binary
stdin/stdout. The fixture directory is required and must come from the
checkout's `tests/data` directory; for example:

```sh
python3 scripts/release/smoke.py \
  --cli .release/unpacked-cli/$TARGET/bin/audiowmark \
  --fixtures tests/data
```

Linux packages are also exercised in clean Alpine and Ubuntu containers without
audio libraries. Those containers mount only the extracted CLI, the smoke
script, and `tests/data` (as `/fixtures`); they have no access to the repository
or builder dependency prefix. Dependency prefix caches are separated by target,
compiler/image identity, source lock, recipe and patch hashes.

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
Ninja, Python 3.9+, patch, and Git. Use the matching native architecture; the
Linux entry point chooses the pinned Alpine image from
`scripts/release/images.lock.json`.

```sh
export TARGET=linux-musl-x86_64 VERSION=1.2.3
scripts/release/container-build.sh
scripts/release/container-smoke.sh
```

The Linux smoke commands above use `tests/data` from the checkout; clean
container smoke receives the same directory as `/fixtures`.

On macOS or in the MINGW64 shell on Windows:

```sh
export TARGET=macos-aarch64 VERSION=1.2.3
export RELEASE_WORK="$PWD/.release/$TARGET"
scripts/release/build.sh
```

`SOURCE_CACHE` can point to the source bundle's absolute `dependencies/`
directory to avoid downloading sources again. `JOBS` defaults to four.
Build scripts copy and stamp the project version in a separate work directory,
leaving the original checkout unchanged. All compiler/linker flags are in
`environment.sh` and `build.sh`; installed dependency archives live in
`RELEASE_WORK/prefix`. Delete that directory after changing build flags unless
using the workflow's matching cache key.
