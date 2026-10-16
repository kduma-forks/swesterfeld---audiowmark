# Consuming the audiowmark native SDK and language packages

Download the SDK and language package from the **same version** of
[GitHub Releases](https://github.com/kduma-forks/swesterfeld---audiowmark/releases).
The native ABI is version 1; its version is independent of the package SemVer.
All packages are GPL-3.0-or-later, as is the upstream audiowmark engine by Stefan
Westerfeld. Releases attach `.crate` and `.nupkg` files; they do not publish to
crates.io or nuget.org.

| SDK target | NuGet RID | Native library |
| --- | --- | --- |
| win7-x86_64 | win-x64 | audiowmark.dll |
| linux-gnu-x86_64 | linux-x64 | libaudiowmark.so |
| linux-gnu-aarch64 | linux-arm64 | libaudiowmark.so |
| linux-musl-x86_64 | linux-musl-x64 | libaudiowmark.so |
| linux-musl-aarch64 | linux-musl-arm64 | libaudiowmark.so |
| macos-x86_64 | osx-x64 | libaudiowmark.dylib |
| macos-aarch64 | osx-arm64 | libaudiowmark.dylib |

Use glibc SDKs on distributions with glibc 2.28 or newer; use musl SDKs on
Alpine. macOS requires version 15 or newer. The Windows native library supports
Windows 7 SP1 x64; use .NET Framework 4.8 or Rust 1.77.2 for Windows 7
applications. A recent .NET runtime has its own OS requirements and is not the
Windows 7 execution target.

## Rust

Rust 1.77.2 is the minimum supported version. Extract the release attachment:

```sh
mkdir -p vendor
tar -xzf audiowmark-0.6.5.crate -C vendor
```

Add the extracted crate as a path dependency:

```toml
[dependencies]
audiowmark = { path = "vendor/audiowmark-0.6.5" }
```

Or pin a release tag in a Git dependency; Cargo discovers the `audiowmark`
package under `bindings/rust`:

```toml
[dependencies]
audiowmark = { git = "https://github.com/kduma-forks/swesterfeld---audiowmark", tag = "v0.6.5" }
```

Use the tag actually present on the release; tags may omit the `v` prefix.
No build script downloads or links a native SDK. Cargo downloads the ordinary
Rust dependency `libloading`. Distribute the matching SDK library with your
application, then load its explicit path:

```rust,no_run
use audiowmark::{Library, Options, Payload};
let library = Library::load("/opt/my-app/native/libaudiowmark.so")?;
let key = library.generate_key("customer-42")?;
let key_text = key.export()?; // CLI-compatible text; persist securely
let imported = library.import_key(&key_text)?;
let mut context = library.context_with_options(&Options {
    workers: 1,
    ..Options::default()
})?;
context.set_keys(&[&imported])?;
let payload = Payload::from_hex("0123456789abcdef0123456789abcdef")?;
context.add_file("input.wav", "marked.wav", payload)?;
let found = context.detect_file("marked.wav")?;
for d in found {
    println!("{} {} {}", d.payload, d.key_name, d.time_seconds);
}
# Ok::<(), audiowmark::Error>(())
```

Load trusted native SDK files: loading executes native initialization code, and
the wrapper relies on that library honoring the published ABI. Library handles,
contexts and keys hold the module alive through `Arc`. Musl applications must
link the dynamic musl runtime: use `RUSTFLAGS='-Ctarget-feature=-crt-static'`
when building for `*-unknown-linux-musl`. The default statically linked musl
runtime cannot load shared libraries with `dlopen`. Contexts can move between
threads (`Send`); `&mut self` operations and `!Sync` prevent concurrent use of one
context. Create separate contexts for parallel work. Passing no keys restores
the public default CLI key; adding uses the first configured key and detection
tries all configured keys.

PCM is interleaved float32. For two channels at 44.1 kHz:

```rust,no_run
# use audiowmark::{Library,Payload};
# let library = Library::load("/opt/my-app/native/libaudiowmark.so")?;
# let mut context = library.context()?;
# let samples = vec![0.0_f32; 44100 * 2];
# let payload = Payload([0; 16]);
let marked = context.add_pcm(&samples, 2, 44100, payload)?;
assert_eq!(marked.len(), samples.len());
let detections = context.detect_pcm(&marked, 2, 44100)?;
# Ok::<(), audiowmark::Error>(())
```

The runnable `examples/rust` consumer exercises file and PCM watermarking, key
round trips, errors, Unicode paths and independent contexts in parallel:

```sh
cargo +1.77.2 run --release --manifest-path examples/rust/Cargo.toml -- \
  /absolute/sdk/lib/libaudiowmark.so input.wav marked.wav /absolute/work-dir
```

The repository example uses `bindings/rust` as its development dependency.
`bindings/test-packages.py` rewrites it to the extracted release crate before
running the package acceptance test.

## C# / NuGet

Place `Audiowmark.0.6.5.nupkg` in a local directory, for example `/opt/local-nuget`.
Create a `NuGet.Config` beside the consuming project:

```xml
<configuration>
  <packageSources>
    <clear />
    <add key="audiowmark-releases" value="/opt/local-nuget" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
  <packageSourceMapping>
    <packageSource key="audiowmark-releases">
      <package pattern="Audiowmark" />
    </packageSource>
    <packageSource key="nuget.org">
      <package pattern="Microsoft.*" />
      <package pattern="NETStandard.Library" />
    </packageSource>
  </packageSourceMapping>
</configuration>
```

Then add a package reference and the deployment RID:

```xml
<PropertyGroup>
  <TargetFramework>net8.0</TargetFramework>
  <RuntimeIdentifier>linux-x64</RuntimeIdentifier>
</PropertyGroup>
<ItemGroup>
  <PackageReference Include="Audiowmark" Version="0.6.5" />
</ItemGroup>
```

The package contains one `netstandard2.0` assembly (`Audiowmark.Managed.dll`)
and seven native RID assets. Its managed filename is distinct from
`audiowmark.dll` on Windows.
NuGet chooses and copies the library to your application; P/Invoke uses that
library. No custom native path or native download is needed. To build the managed
wrapper from source, run `dotnet build bindings/dotnet/Audiowmark/Audiowmark.csproj`;
this does not require native files. They are required only when packing the
release or running native operations.

```csharp
using Audiowmark;
using (var key = Key.Generate("customer-42"))
using (var context = new Context(new Options { Workers = 1 }))
{
    context.SetKeys(key); // copies key; it may be disposed after this call
    var payload = Payload.FromHex("0123456789abcdef0123456789abcdef");
    context.AddFile("input.wav", "marked.wav", payload);
    var detections = context.DetectFile("marked.wav");
    var marked = context.AddPcm(interleavedSamples, 2, 44100, payload);
    var pcmDetections = context.DetectPcm(marked, 2, 44100);
}
```

Every native context and key uses `SafeHandle` and `IDisposable`. Dispose handles
promptly with `using`. Operations and disposal are serialized within a context;
separate contexts run in parallel. `AudiowmarkException.Code` distinguishes
argument, I/O, internal, busy and memory errors. No detected candidates means a
successful empty list. Native result and error handles are freed before returning
to the caller; detection objects retain copied values and names.

All strings are encoded and decoded explicitly as UTF-8, including Windows
paths. PCM output is a separate array of exactly the input length; the input
must contain complete interleaved frames and finite samples. Do not modify an
input array while a synchronous call is using it. Payloads contain 16 bytes.
Detection preserves CLI `get` candidates, including `n-best` guesses; a candidate
under a wrong key does not establish a watermark match. Compare the expected
payload and inspect quality and decoding error for your application.
Options include strength, synchronization threshold, fragment duration in
minutes, speed mode/ratio, `n-best` and workers. Defaults match the CLI, with one
worker per context. Detection records include payload, key index/name, block type
(including clipped blocks), time, quality, decoding error, ranking and speed.

For .NET Framework 4.8, use a `net48` project with `PlatformTarget=x64`. Package
build targets copy `runtimes/win-x64/native/audiowmark.dll` beside the executable,
including publish output. The `build/` target also supports `packages.config`;
`buildTransitive/` carries the rule through PackageReference dependencies.

```sh
dotnet build examples/dotnet/Consumer.csproj -c Release \
  -p:ConsumerFramework=net48 -p:PlatformTarget=x64 -p:AudiowmarkVersion=0.6.5
```

Build on a machine with a supported .NET SDK, then copy the entire `net48`
output directory to Windows 7 SP1 x64 with .NET Framework 4.8 installed. Run
`examples/windows7-smoke.ps1` there. The manual result confirms Windows 7 runtime
compatibility; a current Windows CI runner cannot establish that result.

## C and packaged integration checks

`examples/c/consumer.c` dynamically loads an explicit library path and uses only
the published C header. It exercises files, PCM, key import/export, an error
followed by successful calls, invalid capacity, and results that outlive their
context. See its opening comment for platform-specific build commands.

Release automation calls:

```sh
python3 bindings/package.py --version v0.6.5 --nuget-version 0.6.5 \
  --native-dir native --output-dir dist
python3 bindings/test-packages.py --crate dist/audiowmark-0.6.5.crate \
  --nuget-feed dist --version 0.6.5 --sdk native/linux-gnu-x86_64 \
  --rid linux-x64 --work-dir /tmp/audiowmark-consumers --framework net8.0 \
  --cli /absolute/audiowmark
```

The packer requires all seven matching native libraries before producing either
attachment. It also retains the SDK
third-party notices under `licenses/<rid>` in the NuGet package; retain them
when redistributing the native assets. Its native input is `native/<sdk-target>/lib/<filename>` (RID inputs
`native/<rid>/native/<filename>` are also accepted, with
`native/<rid>/licenses/`). It checks exact runtime asset
paths and hashes inside the `.nupkg`. Versions are validated SemVer with optional
`v`; NuGet omits SemVer build metadata.

The test directory must be empty. Tests compile against the extracted SDK,
consume the actual extracted `.crate`, and restore the actual `.nupkg` into a
fresh cache from the local feed. They use Rust 1.77.2 and .NET 8 by default. The
C# process runs from its test directory without `LD_LIBRARY_PATH` or
`DYLD_LIBRARY_PATH` or `DYLD_FALLBACK_LIBRARY_PATH`. On Windows x64 the script
executes both the modern .NET DLL and the .NET Framework 4.8 EXE from the local
package; `--framework net48` runs the Framework EXE directly. Optional `--cli` checks compatibility in both directions.
`--skip-dotnet` is available only for native hosts without a .NET runtime; such a
run does not establish C# compatibility. CI uses .NET on all supported modern
runtime hosts and keeps Windows 7 testing manual.
