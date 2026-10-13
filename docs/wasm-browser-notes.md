# Browser WebAssembly: future work

This is a starting point for a browser port, not an implementation. No wasm
target or dependency cross-build has been compiled or tested. Porting effort,
browser compatibility, memory limits, and performance remain unknown. The
desktop build stays unchanged; mobile platforms are outside this note.

## Proposed package and first scope

Build the C++ engine and its dependencies with Emscripten, producing a versioned
`.wasm`, JavaScript ES module, and TypeScript wrapper/declarations. Load one
module instance inside a dedicated Web Worker so synchronous DSP does not
block the page. The existing [C API](api.md) and
[header](../include/audiowmark.h) provide the ownership and operation model;
document the browser export subset separately, without claiming full native
ABI equivalence.

Start with interleaved `float32` PCM, a 128-bit payload, contexts/options,
key generation and text import/export, detection results, and typed errors.
For file selection, browser `decodeAudioData()` can supply PCM, but supported
formats depend on the browser and decoding may resample. Interleave its
planar channel data and pass the returned `AudioBuffer.sampleRate`, not an
assumed source rate. Native file/codec support can follow through a virtual
filesystem and additional cross-built codecs; it is not required for the
first PCM package.

## Toolchain and source changes to prove

Choose and validate a supported emsdk/Emscripten version during the first
cross-build; no wasm toolchain has been qualified yet. Then pin SDK/compiler
versions and commits, download SHA256s, and the builder/container identity in
a separate browser lock. Use Emscripten's cross-build tools for every object and
the final link; native archives cannot be reused. Preserve C++ exceptions in
the engine and runtime, including worker-job error propagation and C API
catches. A consistent `-fexceptions` build is a starting option; native wasm
exception handling needs separate browser/toolchain validation.

Two existing constraints need explicit changes:

- [ThreadPool](../src/threadpool.cc) constructs `std::thread` even with
  `workers = 1`. A single-thread wasm build needs a genuine inline executor
  that preserves configuration, completion, and exception semantics.
- [configure.ac](../configure.ac) requires audio dependencies, and the current
  [C API implementation](../src/c-api.cc) contains both file and PCM paths.
  A PCM-only target needs explicit configuration and source separation;
  choosing fewer exported functions alone does not establish that separation.

Actually cross-build FFTW's float variant, zita-resampler, libgcrypt, and
libgpg-error, using the [existing source lock](../scripts/release/dependencies.lock.json)
as a starting point. Begin with portable C/C++ implementations and disable
native assembly and architecture-specific acceleration. Their wasm build and
runtime support are unproven. Supply browser `crypto.getRandomValues()` entropy
for new keys. Preserve the exact deterministic AES-128 ECB/CTR stream,
counter/seed interpretation, and key text format in
[random.cc](../src/random.cc); fresh-key entropy must not change native/CLI
watermark or key compatibility.

## Wrapper, memory, and optional capabilities

The wrapper owns wasm allocations and native handles, copies borrowed text
and results before release, and frees resources after success or failure.
Handle `uint64_t` values deliberately with wasm BigInt interop and checked
conversions. Recreate typed-array views after wasm memory growth. Transfer
buffers between page and Worker where useful, while accounting for copies
into and out of wasm memory. A Promise API over a Worker adds asynchronous
delivery; it does not itself provide streaming, cancellation, or progress.

Ten minutes of stereo 44.1 kHz `float32` PCM occupies **211.68 MB** for one
buffer (decimal MB). Current
[`audiowmark_add_pcm`](../src/c-api.cc) also requires separate output storage
and accumulates a temporary `PCMOutput`, before counting JavaScript copies,
decoded audio, and DSP workspaces. Choose measured recording/heap budgets and
reject oversized requests predictably. Streaming requires a future stateful
API, not merely passing smaller chunks to the current operation.

Optional wasm threads require `SharedArrayBuffer` and cross-origin isolation
with COOP/COEP headers. Treat them as a distinct build with a tested
single-thread fallback. Consider optional SIMD only after correctness checks
and representative browser benchmarks.

## Acceptance and distribution

Run actual compiled wasm in Chromium, Firefox, and WebKit. Test both directions
of native/wasm payload and key interoperability, Unicode key text, malformed
PCM, typed errors, recovery, repeated handle/allocation lifetimes, and memory
growth/budgets. Include the single-thread fallback and any optional variant.
Ship matching versioned wasm, JS, `.d.ts`, a Worker example, corresponding
sources/build recipes, and dependency notices. The project's
[GPLv3-or-later license](../COPYING) continues to apply; browser delivery does
not change it.
