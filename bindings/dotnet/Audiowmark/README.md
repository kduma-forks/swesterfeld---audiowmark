# Audiowmark

`netstandard2.0` bindings to audiowmark ABI 1, including native libraries for
win-x64, linux-x64, linux-arm64, linux-musl-x64, linux-musl-arm64, osx-x64 and
osx-arm64. GPL-3.0-or-later; see LICENSE. Builds of the managed sources do not
require a native SDK.

Download `Audiowmark.VERSION.nupkg` from the same GitHub Release as the SDK,
put it in a local directory, and add that directory as a NuGet source. Add
`<PackageReference Include="Audiowmark" Version="VERSION" />` to your project.
No package is published to nuget.org. Native SDK third-party license notices
are retained under `licenses/<rid>`; keep these notices when redistributing
the corresponding native libraries.

```csharp
using (var context = new Audiowmark.Context())
{
    var payload = Audiowmark.Payload.FromHex("0123456789abcdef0123456789abcdef");
    context.AddFile("input.wav", "marked.wav", payload);
    foreach (var detection in context.DetectFile("marked.wav"))
        Console.WriteLine(detection.Payload);
}
```

Set `RuntimeIdentifier` to the target RID for deployment. A .NET Framework 4.8
project must set `PlatformTarget` to `x64`; the package copies its win-x64 DLL
beside the executable. .NET Framework 4.8 x64 on Windows 7 SP1 is covered by
the manual smoke instructions shipped in the SDK.

All native text uses explicit UTF-8, even on Windows. Contexts and keys use
SafeHandle and IDisposable. Operations on one context are serialized;
independent contexts can run in parallel. Native errors become
`AudiowmarkException`, and no detections is an empty list. Interleaved PCM
uses float32 samples with a separate output array and 128-bit payloads.
