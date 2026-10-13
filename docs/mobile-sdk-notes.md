# Android and iOS SDKs: future work

This is a starting point, not an implemented mobile SDK. A medium-complexity
native port appears plausible, with likely less engine adaptation than the
[browser wasm proposal](https://github.com/kduma-forks/swesterfeld---audiowmark/pull/2); that assessment is unverified.
No Android NDK or iOS cross-build, emulator/simulator run, or device test has
been performed. No toolchain or minimum OS version has been qualified. Desktop
packages stay unchanged.

The existing [C API](api.md), [header](../include/audiowmark.h), ARM64 desktop
support, context ownership, and separation of library and CLI are foundations.
CPU identity alone does not imply platform compatibility.

## Proposed platforms and packaging

For Android, build a Bionic-compatible `.so` and distribute an AAR containing
JNI bindings and a Kotlin/Java wrapper. Start with `arm64-v8a` plus `x86_64`
for emulator coverage. Desktop Linux libraries cannot be reused. Select a
minimum Android API and qualify an NDK/Clang combination before pinning its
versions, download hashes, and builder identity. Align C++ runtime linkage with
the consuming app. Ensure **16 KB page-size support** in every shared library
and in final app packaging; test installation and execution on that environment.
Use the official [page-size guidance](https://developer.android.com/guide/practices/page-sizes)
and [NDK build-system guidance](https://developer.android.com/ndk/guides/other_build_systems).

For iOS, prefer a static XCFramework with a Swift wrapper and Swift Package
Manager distribution. Build separate ARM64 device and ARM64 simulator slices
against their respective SDKs, optionally adding an x86_64 simulator slice.
Select a minimum deployment version and qualify/pin Xcode, SDK, compiler, and
builder versions. An ARM64 macOS archive or device archive cannot substitute
for a simulator build. Static packaging is the initial preference, not a claim
that iOS universally prohibits dynamic linking.

## Cross-build work to prove

Adapt the [desktop build recipe](../scripts/release/build.sh) and
[pinned source lock](../scripts/release/dependencies.lock.json), rather than
reusing desktop binaries. Cross-build FFTW's float variant, zita-resampler,
libgcrypt, libgpg-error, and the required audio codecs. Separate build-host
tools from target objects; set explicit sysroots and compiler targets. Use
distinct dependency prefixes and cache keys for each ABI, platform SDK,
deployment minimum, toolchain, and recipe/source hash. Current release
environment checks assume native `uname` architecture and need adaptation.

Preserve C++ exceptions and C ABI error translation. First prove portable
dependency implementations, then qualify assembly and acceleration. Review
dependency Apple environment and spawn APIs for iOS availability: existing
macOS patches do not establish iOS support. A PCM-focused proof still needs
explicit source/configuration separation where current builds require codec
dependencies. Exclude HLS, FFmpeg, and videowmark from the initial mobile package.

## App adapters and first API scope

Start with background/offline file and interleaved `float32` PCM add/detect,
128-bit payloads, keys, options, results, and errors. Preserve the C ABI's
ownership, UTF-8 handling, key serialization, and deterministic watermark/key
compatibility with desktop and CLI. Verify platform entropy for new keys
without changing deterministic cryptographic streams.

Android content URIs and iOS sandbox/document access require app adapters;
they are not ordinary native paths. Copy authorized input into app storage or
decode to PCM. AAC/M4A can use Android MediaCodec or Apple AVFoundation without
FFmpeg. Pass actual decoded sample rates and channel layouts, converting to
interleaved float samples. Native `add_file` writes WAV; producing AAC/M4A
output needs a separate app encoder.

Run synchronous operations off the UI thread. JNI and Swift wrappers must
retain handles and buffers for each call, copy borrowed results before release,
and free resources on errors. Use separate contexts for concurrent operations.
The [desktop Rust/NuGet packages](bindings.md) do not automatically supply
mobile support: Rust `libloading` and NuGet native assets need platform-specific
work, including static iOS bindings and packaging.

Live microphone processing, stateful streaming, progress, and cancellation
are not provided by the current ABI. Profile real phones for memory, PCM
copies, detection speed-search settings, worker counts, battery, and thermal
behavior before selecting limits or promising latency.

## Proof stages and acceptance

First produce ARM64 Android and iOS PCM/key builds. Then add AAR/XCFramework
packaging, wrappers, sample apps, file adapters, compatibility tests, and
performance measurements. Test the actual distributed packages in Android
emulators, iOS simulators, and real devices. Exercise desktop/mobile keys and
watermarks both ways, Unicode, errors, repeated lifetimes, and concurrent
independent contexts. Existing `testapi` invokes the CLI through `system`;
adapt reference fixtures and a mobile harness rather than running it unchanged
on iOS.

Ship matching sources, build recipes, dependency notices, and version metadata.
The project's [GPLv3-or-later license](../COPYING) and dependency license/source
obligations remain applicable. Assess intended app-store and other distribution
arrangements for compatibility before shipping; this note makes no categorical
legal determination.
