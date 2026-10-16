#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${VERSION:?}"
[[ $TARGET == linux-musl-* ]] || { echo 'container-build requires a Linux musl CLI target' >&2; exit 1; }
image=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["alpine"])')
docker run --rm --network host -v "$ROOT:/work" -w /work -e TARGET -e VERSION -e JOBS="${JOBS:-4}" \
 -e RELEASE_WORK="/work/.release/$TARGET" -e RELEASE_OUTPUT=/work/dist "$image" \
 sh -ec 'apk add --no-cache bash build-base autoconf automake libtool pkgconf cmake ninja python3 curl patch git linux-headers gettext-dev
 git config --global --add safe.directory /work
 bash scripts/release/build.sh
 python3 scripts/release/unpack.py --artifacts dist --cli .release/unpacked-cli
 python3 scripts/release/smoke.py --cli ".release/unpacked-cli/$TARGET/bin/audiowmark"'
