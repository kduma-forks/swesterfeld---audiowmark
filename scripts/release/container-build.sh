#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${VERSION:?}"
export VARIANT="${VARIANT:-cli}"
[[ $VARIANT == cli || $VARIANT == full ]] || { echo 'VARIANT must be cli or full' >&2; exit 1; }
[[ $TARGET == linux-musl-* ]] || { echo 'container-build requires a Linux musl CLI target' >&2; exit 1; }
image=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["alpine"])')
docker run --rm --network host -v "$ROOT:/work" -w /work -e TARGET -e VERSION -e VARIANT -e JOBS="${JOBS:-4}" \
 -e RELEASE_WORK="/work/.release/$VARIANT/$TARGET" -e RELEASE_OUTPUT=/work/dist "$image" \
 sh -ec 'apk add --no-cache bash build-base autoconf automake libtool pkgconf cmake ninja python3 curl patch git linux-headers gettext-dev nasm
 git config --global --add safe.directory /work
 bash scripts/release/build.sh
 python3 scripts/release/unpack.py --artifacts dist --variant "$VARIANT" --cli ".release/unpacked-$VARIANT"
 python3 scripts/release/smoke.py --cli ".release/unpacked-$VARIANT/$TARGET/bin/audiowmark" --variant "$VARIANT" --full-tests tests/full-test.py'
