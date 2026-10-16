# Native C SDK (ABI 1)

The public contract is `audiowmark.h`. The SDK is GPL-3.0-or-later, like the CLI.
Build with Autotools (`autoreconf -fi`, configure, make, make install). The CLI
links its own engine archive and does not require the SDK shared library.
Installed files include `include/audiowmark.h`, the library in `lib`, and this
reference in `share/doc/audiowmark`. Windows builds install `audiowmark.dll` and
its matching import library. Linux uses `libaudiowmark.so.1`; macOS uses
`libaudiowmark.1.dylib`. `--disable-videowmark` omits the auxiliary video script.

`AUDIOWMARK_CLI_LDFLAGS` affects the CLI only, allowing libtool `-all-static` for musl.
`AUDIOWMARK_SHARED_LDFLAGS` affects the SDK only, allowing `-static-libstdc++
-static-libgcc -Wl,--exclude-libs,ALL` on Linux/Windows. Supply PIC static dependency
archives and `PKG_CONFIG='pkg-config --static'` (or `--enable-static-deps`) for
self-contained SDK dependency linkage. Do not pass `-static` in global LDFLAGS
when building a shared SDK. Internal engine symbols have hidden visibility and
SDK exports are restricted to `audiowmark_*`. Release builds omit FFmpeg.

## Calls and ownership

Call `audiowmark_options_init`, then edit desired fields and create a context.
NULL options uses defaults. Options ABI1 is 56 bytes; the initializer always
writes exactly this size. Any future struct expansion needs a new initializer
so it cannot overwrite storage supplied by an ABI1 caller. Larger structs are
accepted when their initial ABI1 layout and ABI version remain compatible.
The immutable context owns its configuration and copies keys passed to
`audiowmark_context_set_keys`. Independent contexts process audio concurrently;
one context permits one active operation. Simultaneous use returns ERROR_BUSY.
The caller must synchronize handle destruction with all calls using that handle.

All operation functions return int32 status, zero for success. Optional error
output receives NULL on success or a newly owned error on failure. Free each
error before reusing its output slot. Allocation failure may return ERROR_MEMORY
without an error handle. Create/detect outputs receive NULL on failure. Owned
keys/results/errors remain valid independently of context lifetime. Release
handles only with the corresponding native free function. NULL frees are safe.
Borrowed text and names remain valid until their key/result is freed; version
text has library lifetime. The library is quiet and does not change host streams.
Exceptions from workers are collected after all jobs complete and returned as
structured errors; errors do not prevent later calls on the context.

## Audio and results

Add/detect payloads are exactly 16 bytes, in the same order as CLI hexadecimal
text. Float PCM is interleaved; `frames` counts complete frames and output
capacity counts individual float samples. The input must be finite. Channels
range from 1 to 64; rates range from 8000 to 384000 Hz. Output is a separate,
nonoverlapping caller buffer, with the exact input length, rate and channel count.
Empty PCM is valid and detection returns an empty result. PCM add fills the
caller output only after success. PCM/file detection uses the same bounded,
overlapping chunk algorithm as the CLI, including speed correction.

Paths are UTF-8 on all platforms. File API rejects `-` and aliased input/output
files (including hard links and symlinks). File output is WAV with the input
precision preserved where supported. File writes may leave partial output on
I/O failure; callers may use their own temporary path and rename after success.
Input decoding follows the native CLI formats (libsndfile and mpg123).

Detection structs are 64 bytes. Candidate rows contain payload, copied key-list
index, block type, time, synchronization quality, decoder error, ranking and
speed ratio. Block types distinguish A/B/AB/ALL and CLIP_A/B/AB; ALL time is -1.
Result name lookup returns the copied UTF-8 CLI key name; key index refers to
position in the context's copied list, or zero for the default public key.
No candidates is a successful, owned result with count zero. Detection candidates
may include false positives; applications should evaluate quality, error and
agreement across repeated blocks rather than treating every candidate as verified.

Strength is in CLI units (default 10, range greater than zero through 1000).
Synchronization threshold defaults to .35 (range 0..1), n_best to 8 (0..4096),
chunk size to 30 minutes (10..1440), speed ratio to 1 (.5..2), and worker limit to
1 (1..256). NONE/DETECT/PATIENT/MANUAL choose speed behavior. CLI defaults and
short/test payload modes remain separate from the library's fixed payload128.

Keys generate/import/export/load/save in the CLI text format. Names must be
valid UTF-8 without control characters; quotes and backslashes are escaped.
A zero-length key list restores the CLI public default key. Adding uses the first
key; detection tries all configured keys. Keys are copied, so callers may free
key handles immediately after setting them.

Windows builds target Win7 through `_WIN32_WINNT=0x0601` and `WINVER=0x0601`,
MSVCRT toolchains and UTF-16 filesystem calls internally. Only CLI entry sets
stdin/stdout binary mode; the library never alters those streams. Win7 runtime
acceptance must be verified on an actual Windows 7 SP1 x64 system.
