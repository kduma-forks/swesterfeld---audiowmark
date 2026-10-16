#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${RID:?}" "${VERSION:?}" "${NUGET:?}"
image=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["alpine"])')
docker run --rm --network host -v "$ROOT:/work" -w /work -e TARGET -e RID -e VERSION -e NUGET "$image" sh -ec '
 apk add --no-cache bash build-base python3 curl ca-certificates dotnet8-sdk icu-libs libgcc
 export DOTNET_CLI_TELEMETRY_OPTOUT=1
 # libloading needs dynamic musl to dlopen the SDK.
 export RUSTFLAGS="${RUSTFLAGS:+$RUSTFLAGS }-Ctarget-feature=-crt-static"
 curl --proto "=https" --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup.sh
 sh /tmp/rustup.sh -y --profile minimal --default-toolchain 1.77.2
 export PATH="$HOME/.cargo/bin:$PATH"
 python3 bindings/test-packages.py --crate "dist/audiowmark-$VERSION.crate" --nuget-feed dist --version "$NUGET" --sdk "native/$TARGET" --rid "$RID" --work-dir /tmp/consumers --framework net8.0 --cli "/work/cli/$TARGET/bin/audiowmark"'
