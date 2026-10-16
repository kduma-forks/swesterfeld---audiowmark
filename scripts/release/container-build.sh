#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${VERSION:?}"
case "$TARGET" in
 linux-musl-*) image=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["alpine"])') ;;
 linux-gnu-*) arch=${TARGET##*-}; image=$(python3 -c 'import json,sys; print(json.load(open("scripts/release/images.lock.json"))["manylinux-"+sys.argv[1]])' "$arch") ;;
 *) echo 'container-build is only for Linux' >&2; exit 1 ;;
esac
docker run --rm --network host -v "$ROOT:/work" -w /work -e TARGET -e VERSION -e JOBS="${JOBS:-4}" \
 -e RELEASE_WORK="/work/.release/$TARGET" -e RELEASE_OUTPUT=/work/dist "$image" \
 sh -ec 'if command -v apk >/dev/null; then
   apk add --no-cache bash build-base autoconf automake libtool pkgconf cmake ninja python3 curl patch git linux-headers gettext-dev
 else
   export PATH=/opt/python/cp311-cp311/bin:$PATH
   yum install -y autoconf automake libtool pkgconfig gettext-devel patch ninja-build
 fi
 git config --global --add safe.directory /work
 bash scripts/release/build.sh
 python3 scripts/release/unpack.py --artifacts dist --native .release/unpacked --cli .release/unpacked-cli
 if [ "${TARGET#linux-musl-}" != "$TARGET" ]; then
   python3 scripts/release/smoke.py --sdk ".release/unpacked/$TARGET" --cli ".release/unpacked-cli/$TARGET/bin/audiowmark"
 else
   python3 scripts/release/smoke.py --sdk ".release/unpacked/$TARGET"
 fi'
