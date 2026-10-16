# Rust consumer

Requires Rust 1.77.2 and the matching native SDK. In the source checkout the
example uses `../../bindings/rust`. In an extracted SDK, download and extract the
release `.crate`, then replace that dependency with its absolute path:

```toml
[dependencies]
audiowmark = { path = "/absolute/vendor/audiowmark-VERSION" }
```

Run with a WAV file of at least 40 seconds and an existing writable work directory:

```sh
cargo +1.77.2 run --release --manifest-path Cargo.toml -- \
  /absolute/sdk/lib/libaudiowmark.so input.wav marked.wav /absolute/work
```

Use `audiowmark.dll` on Windows or `libaudiowmark.dylib` on macOS. Alpine/musl
applications must use the dynamic musl runtime to support `dlopen`:

```sh
RUSTFLAGS='-Ctarget-feature=-crt-static' cargo +1.77.2 run --release -- \
  /absolute/sdk/lib/libaudiowmark.so input.wav marked.wav /absolute/work
```

The example validates files, mono/stereo PCM at 32/44.1 kHz, key text/files,
Unicode paths, empty/silent PCM, errors, handle lifetimes and parallel contexts.
Results include CLI `get` candidates; tests compare known payloads rather than
assuming every candidate is a confirmed watermark.
