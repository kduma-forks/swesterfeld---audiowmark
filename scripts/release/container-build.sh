#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${VERSION:?}"
export VARIANT="${VARIANT:-cli}"
[[ $VARIANT == cli || $VARIANT == full ]] || { echo 'VARIANT must be cli or full' >&2; exit 1; }
case "$TARGET" in
 linux-musl-*) image=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["alpine"])') ;;
 linux-gnu-*)
   [[ $VARIANT == cli ]] || { echo 'GNU targets only build the SDK in the cli variant' >&2; exit 1; }
   arch=${TARGET##*-}; image=$(python3 -c 'import json,sys; print(json.load(open("scripts/release/images.lock.json"))["manylinux-"+sys.argv[1]])' "$arch") ;;
 *) echo 'container-build is only for Linux' >&2; exit 1 ;;
esac
docker run --rm --network host -v "$ROOT:/work" -w /work -e TARGET -e VERSION -e VARIANT -e JOBS="${JOBS:-4}" \
 -e RELEASE_WORK="/work/.release/$VARIANT/$TARGET" -e RELEASE_OUTPUT=/work/dist "$image" \
 sh -ec 'if command -v apk >/dev/null; then
   apk add --no-cache bash build-base autoconf automake libtool pkgconf cmake ninja python3 curl patch git linux-headers gettext-dev nasm
 else
   export PATH=/opt/python/cp311-cp311/bin:$PATH
   yum install -y autoconf automake libtool pkgconfig gettext-devel patch ninja-build
 fi
 git config --global --add safe.directory /work
 bash scripts/release/build.sh
 python3 scripts/release/unpack.py --artifacts dist --native .release/native --variant "$VARIANT" --cli ".release/unpacked-$VARIANT"
 if [ "$VARIANT" = full ]; then
   python3 scripts/release/smoke.py --cli ".release/unpacked-full/$TARGET/bin/audiowmark" --fixtures tests/data --variant full --full-tests tests/full-test.py
 elif [ "${TARGET#linux-musl-}" != "$TARGET" ]; then
   python3 scripts/release/smoke.py --sdk ".release/native/$TARGET" --cli ".release/unpacked-cli/$TARGET/bin/audiowmark" --fixtures tests/data
 else
   python3 scripts/release/smoke.py --sdk ".release/native/$TARGET"
 fi'
