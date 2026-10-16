#!/usr/bin/env bash
# Mount only extracted packages and the smoke script: builder prefix is inaccessible.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}"
SDK_DIR="$ROOT/.release/unpacked/$TARGET"
CLI_TARGET=${TARGET/linux-gnu-/linux-musl-}
CLI_DIR="$ROOT/.release/unpacked-cli/$CLI_TARGET"
image_key=ubuntu
[[ $TARGET != linux-musl-* ]] || image_key=alpine
image=$(python3 -c 'import json,sys; print(json.load(open("scripts/release/images.lock.json"))[sys.argv[1]])' "$image_key")
mounts=(-v "$SDK_DIR:/sdk:ro" -v "$ROOT/scripts/release/smoke.py:/smoke.py:ro")
[[ ! -d $CLI_DIR ]] || mounts+=(-v "$CLI_DIR:/cli:ro")
docker run --rm --network host "${mounts[@]}" "$image" sh -ec '
 if command -v apk >/dev/null; then apk add --no-cache python3; else apt-get update && apt-get install -y --no-install-recommends python3; fi
 if [ -e /cli/bin/audiowmark ]; then python3 /smoke.py --sdk /sdk --cli /cli/bin/audiowmark; else python3 /smoke.py --sdk /sdk; fi'
# A musl CLI must also work on glibc Ubuntu, with no audio library installations.
if [[ $TARGET == linux-musl-* ]]; then
 ubuntu=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["ubuntu"])')
 docker run --rm --network host -v "$CLI_DIR:/cli:ro" "$ubuntu" /cli/bin/audiowmark --version
fi
