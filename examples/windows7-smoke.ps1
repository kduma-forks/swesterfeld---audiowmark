# GPL-3.0-or-later. Run on Windows 7 SP1 x64 with .NET Framework 4.8.
# Copy the CLI, extracted win7-x86_64 SDK, and whole packaged net48 consumer
# output directory to this machine. This script needs no build tools.
param(
    [Parameter(Mandatory=$true)][string]$Cli,
    [Parameter(Mandatory=$true)][string]$Sdk,
    [Parameter(Mandatory=$true)][string]$Consumer,
    [string]$CConsumer = "",
    [string]$RustConsumer = "",
    [string]$WorkDir = "audiowmark-win7-smoke"
)
$ErrorActionPreference = "Stop"
if ([IntPtr]::Size -ne 8) { throw "Use 64-bit Windows PowerShell." }
$Cli = (Resolve-Path $Cli).Path
$Sdk = (Resolve-Path $Sdk).Path
$Consumer = (Resolve-Path $Consumer).Path
$Library = Join-Path $Sdk "lib\audiowmark.dll"
if (-not (Test-Path $Library)) { throw "SDK DLL missing: $Library" }
$AppLibrary = Join-Path (Split-Path -Parent $Consumer) "audiowmark.dll"
if (-not (Test-Path $AppLibrary)) { throw "net48 consumer output must include the DLL copied from NuGet." }
if ($CConsumer -ne "") { $CConsumer = (Resolve-Path $CConsumer).Path }
if ($RustConsumer -ne "") { $RustConsumer = (Resolve-Path $RustConsumer).Path }
if (-not (Test-Path $WorkDir)) { New-Item -ItemType Directory -Path $WorkDir | Out-Null }
$WorkDir = (Resolve-Path $WorkDir).Path
$InputWav = Join-Path $WorkDir "input.wav"
$CliWav = Join-Path $WorkDir "cli-marked.wav"
$NetWav = Join-Path $WorkDir "net48-marked.wav"
$Payload = "0123456789abcdef0123456789abcdef"
& $Cli --version
if ($LASTEXITCODE -ne 0) { throw "CLI version failed" }
& $Cli test-gen-noise $InputWav 40 44100
if ($LASTEXITCODE -ne 0) { throw "CLI noise generation failed" }
& $Cli add $InputWav $CliWav $Payload
if ($LASTEXITCODE -ne 0) { throw "CLI add failed" }
& $Cli cmp $CliWav $Payload
if ($LASTEXITCODE -ne 0) { throw "CLI detection failed" }
# The net48 consumer loads its app-local NuGet DLL and tests Unicode key paths,
# file/PCM watermarking, key roundtrips, errors and parallel contexts.
& $Consumer $InputWav $NetWav $WorkDir
if ($LASTEXITCODE -ne 0) { throw "net48 DLL consumer failed" }
& $Cli cmp (Join-Path $WorkDir "csharp-default.wav") $Payload
if ($LASTEXITCODE -ne 0) { throw "CLI could not decode the net48 DLL output" }
if ($CConsumer -ne "") {
    & $CConsumer $Library $InputWav (Join-Path $WorkDir "c-marked.wav")
    if ($LASTEXITCODE -ne 0) { throw "C DLL consumer failed" }
}
if ($RustConsumer -ne "") {
    & $RustConsumer $Library $InputWav (Join-Path $WorkDir "rust-marked.wav") $WorkDir
    if ($LASTEXITCODE -ne 0) { throw "Rust 1.77.2 DLL consumer failed" }
}
Write-Output "Windows 7 CLI/DLL/net48 checks passed. Record OS/SP/.NET versions and this output with the release validation."
