# Portable releases

The `Portable release packages` workflow builds five CLI archives, seven C ABI
SDK archives, a Rust `.crate`, a C# `.nupkg`, corresponding sources, licenses,
and `SHA256SUMS`. It runs on pull requests, manual dispatches, and
`release: published` (including prereleases). Pull request and manual builds
only upload workflow artifacts. They never modify a Release or publish to a
package registry.

| Target suffix | CLI | SDK | Runtime requirement |
| --- | --- | --- | --- |
| `win7-x86_64` | EXE | `audiowmark.dll` | Windows 7 SP1 x64 or newer, MSVCRT |
| `linux-musl-x86_64` | fully static | `libaudiowmark.so` | SDK: musl x86_64 |
| `linux-musl-aarch64` | fully static | `libaudiowmark.so` | SDK: musl ARM64 |
| `linux-gnu-x86_64` | use musl CLI | `libaudiowmark.so` | glibc 2.28+ x86_64 |
| `linux-gnu-aarch64` | use musl CLI | `libaudiowmark.so` | glibc 2.28+ ARM64 |
| `macos-x86_64` | executable | `libaudiowmark.dylib` | macOS 15+ Intel |
| `macos-aarch64` | executable | `libaudiowmark.dylib` | macOS 15+ Apple Silicon |

Audio, resampling and cryptography dependencies are built from the pinned
sources in `scripts/release/dependencies.lock.json`. Their recursive codec
sources include Ogg, Vorbis, FLAC and Opus; MP3 decoding uses mpg123. The shared
SDK links PIC archives and exports exactly the public `audiowmark_*` functions.
Linux and Windows link the C++ and GCC runtimes statically; macOS uses Apple's
system libc++ and libSystem. The CLI never needs the SDK beside it. Packages
exclude FFmpeg, HLS and `videowmark`. Builds do not use `-march=native`.

Windows builds use MSYS2 **MINGW64/MSVCRT**, with `WINVER` and `_WIN32_WINNT`
set to `0x0601`. MSYS2 provides the compiler and build tools; all audio
libraries are built from source. UCRT and prebuilt MSYS2 audio libraries are
not used. Modern Windows CI verifies imports, SDK/CLI use outside MSYS2, and
.NET Framework 4.8 consumers. Actual Windows 7 SP1 execution remains a manual
acceptance check; see [the bindings guide](bindings.md). No Authenticode,
Developer ID certificate or notarization is required. macOS binaries receive
an ad hoc signature after their install names are finalized.

## Release process

1. Review and merge the implementation. Run the workflow manually first and
   download its artifacts. Confirm all native and consumer jobs pass; perform
   the supplied Windows 7 manual tests on Windows 7 SP1 x64.
2. Create a tag on the intended commit. Tags must be SemVer with an optional
   `v`, for example `v1.2.3` or `v1.2.3-rc.1`. Build metadata is preserved in
   Rust/package metadata and stripped from the NuGet version.
3. Create and publish the existing GitHub Release for that tag, optionally as
   a prerelease. Publication triggers an exact tag checkout. The workflow
   checks the tag resolves to the checkout commit.
4. All seven native builds, sources, language packaging, all seven packaged
   C/Rust/C# consumer jobs and separate ASan/UBSan and TSan jobs must succeed.
   The read-only verification job checks all 16 assets, writes `SHA256SUMS`,
   and saves the complete `release-assets` workflow artifact on every run.
   The default token is read-only; only the final Release upload job gets
   `contents: write`. It rechecks those checksums and uploads with
   `gh release upload --clobber`. It never creates or publishes a Release.
   Rerunning updates assets with its own deterministic names and preserves
   other Release assets. There is no crates.io or nuget.org publication.

Manual and PR versions are `0.0.0-dev.<commit>`. Manual workflow dispatch does
not accept a publication option. Downloadable workflow artifacts remain
available for the first full build before any Release exists.

## Layout and verification

Archive roots are `audiowmark-VERSION-{cli,sdk}-TARGET`. CLIs have `bin/`;
SDKs have `lib/`, `include/audiowmark.h`, `docs/`, `examples/`, `licenses/`,
`build-scripts/` and `metadata.json`. Linux SDKs include the ABI-1 SONAME link.
The SDK unpack script restores them to `native/TARGET/`, the common bindings
packaging interface. [The C API documentation](api.md) describes ownership,
threading and ABI rules.

Each native package build runs the complete `make check` CLI regression suite,
audits native binary OS imports, architecture, runtime/deployment versions, and
SDK exports, then tests extracted packages from an unrelated directory. The
WAV test is a single `add`/`get` round trip; the unconditional RAW round trip
uses two `add` calls with two keys and two payloads. Format coverage decodes the
real prerecorded synthetic `marked.flac`, `marked.mp3`, `marked.ogg` (Vorbis),
and `marked.opus` fixtures without FFmpeg or Python. Release builds continue to
exclude FFmpeg, HLS, and `videowmark`.

The extracted CLI smoke runs from an unrelated temporary working directory and
adds direct `get`, both JSON output modes fully parsed for validation, exact
payloads, Unicode key names and paths, binary stdin/stdout checks, and all four
fixture codecs. The required fixture directory comes from the checkout's
`tests/data` directory; for example:

```sh
python3 scripts/release/smoke.py \
  --cli .release/unpacked-cli/$TARGET/bin/audiowmark \
  --fixtures tests/data
```

Consumer jobs use the actual `.crate` and local NuGet package feed with Rust
1.77.2 and .NET 8. Windows additionally exercises net48. Alpine Rust consumers
use `RUSTFLAGS=-Ctarget-feature=-crt-static`: a musl application loading the
shared SDK must use the dynamic musl runtime. The CLI remains fully static.
Alpine consumers run on musl; glibc SDKs are built and loaded in the pinned
manylinux glibc-2.28 environment. Linux static CLIs are also run in clean
containers without builder audio libraries; those containers mount only the
extracted SDK/CLI packages, smoke script, and CLI fixtures. Dependency prefix
caches are separated by target, compiler/image identity, source lock, recipe
and patch hashes.

Separate ASan/UBSan and TSan builds run the instrumented C API suite and
thread-pool regressions explicitly, including parallel contexts, key and
buffer ownership, worker exceptions and shutdown. ASan leak detection stays
enabled. The seven normal native builds run the full CLI regression suite.

Check downloaded assets before use:

```sh
sha256sum -c SHA256SUMS
```

The source archive contains the exact project commit, each locked source
archive, the zita static patch, manifests and build recipes. Binary archives
carry upstream notices for the sources actually linked. The standalone
licenses archive contains their union, including GPL and GCC Runtime Library
Exception notices. Compiler executables are not redistributed.

## Reproduce a native build

Install Autoconf, Automake, Libtool, pkg-config, a C/C++ compiler, Make, CMake,
Ninja, Python 3.9+, patch, and Git. Use the matching native architecture; the
Linux entry point chooses pinned Alpine/manylinux images from
`scripts/release/images.lock.json`.

```sh
export TARGET=linux-musl-x86_64 VERSION=1.2.3
scripts/release/container-build.sh
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
