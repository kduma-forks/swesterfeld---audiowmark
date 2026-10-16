# audiowmark

Safe Rust bindings to audiowmark ABI 1. Requires Rust 1.77.2 or newer and the
matching native SDK from the same GitHub Release. The crate loads an explicit
library path with `libloading`; builds never download native code.

```rust,no_run
use audiowmark::{Library, Payload};
let library = Library::load("/opt/audiowmark/lib/libaudiowmark.so")?;
let mut context = library.context()?;
context.add_file("input.wav", "marked.wav", Payload::from_hex(
    "0123456789abcdef0123456789abcdef")?)?;
for detection in context.detect_file("marked.wav")? {
    println!("{} at {} s", detection.payload, detection.time_seconds);
}
# Ok::<(), audiowmark::Error>(())
```

Download `audiowmark-VERSION.crate`, extract it, and use
`audiowmark = { path = "vendor/audiowmark-VERSION" }`. Alternatively pin a Git dependency to the actual release tag:

```toml
audiowmark = { git = "https://github.com/kduma-forks/swesterfeld---audiowmark", tag = "<release-tag>" }
```

Cargo finds the named package under `bindings/rust` in the repository.
There is no crates.io publication. Keep the native SDK beside your application
and pass its absolute library path at runtime. On Windows the filename is
`audiowmark.dll`; on macOS it is `libaudiowmark.dylib`. Applications targeting
`*-unknown-linux-musl` must use a dynamically linked musl runtime: build with
`RUSTFLAGS='-Ctarget-feature=-crt-static'`, since static musl cannot `dlopen`
shared SDK libraries.

Contexts own their options and keys. A context may move to another thread,
but mutable borrowing and `!Sync` prevent concurrent use. Independent contexts
can run in parallel. Keys, native errors and native result handles are freed in
the library which allocated them. Contexts and keys keep that library loaded.
PCM uses interleaved `f32` samples and a separate output buffer; payloads are
128 bits. Native paths and text use UTF-8, including on Windows.

GPL-3.0-or-later; see LICENSE. The SDK has the same GPL license.
