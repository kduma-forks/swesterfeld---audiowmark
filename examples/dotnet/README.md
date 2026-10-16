# C# package consumer

Download `Audiowmark.VERSION.nupkg` into a local feed directory. Create a
`NuGet.Config` beside this project (see `docs/bindings.md` for source mapping):

```xml
<configuration>
  <packageSources>
    <clear />
    <add key="release" value="/absolute/local-feed" />
    <add key="nuget.org" value="https://api.nuget.org/v3/index.json" />
  </packageSources>
</configuration>
```

Use the native target RID (`win-x64`, `linux-x64`, `linux-arm64`,
`linux-musl-x64`, `linux-musl-arm64`, `osx-x64` or `osx-arm64`):

```sh
dotnet build Consumer.csproj -c Release -p:AudiowmarkVersion=VERSION \
  -p:RuntimeIdentifier=linux-x64
dotnet bin/Release/net8.0/linux-x64/Consumer.dll \
  input.wav marked.wav /absolute/work
```

The input WAV should be at least 40 seconds; the work directory must exist.
The package chooses the native library; keep all build/publish output files
when moving the consumer to another machine.

Build the .NET Framework 4.8 x64 example on a machine with a supported SDK:

```sh
dotnet build Consumer.csproj -c Release -p:ConsumerFramework=net48 \
  -p:PlatformTarget=x64 -p:AudiowmarkVersion=VERSION
```

Copy the entire `bin/Release/net48` output directory to Windows 7 SP1 x64 with
.NET Framework 4.8 installed, then run `Consumer.exe input.wav marked.wav WORK`.
`../windows7-smoke.ps1` also checks the release CLI and DLL consumers.

This project uses a real PackageReference, never a project reference to the
wrapper. It checks file and PCM watermarking, key text/files, explicit UTF-8
paths/names, typed errors, disposal, and parallel independent contexts.
