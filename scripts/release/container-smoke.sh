#!/usr/bin/env bash
# Mount only extracted SDK/CLI packages, the smoke script, and CLI fixtures; the repository and builder prefix stay inaccessible.
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
smoke_args=(--sdk /sdk)
if [[ -d $CLI_DIR ]]; then
  mounts+=(-v "$CLI_DIR:/cli:ro" -v "$ROOT/tests/data:/fixtures:ro")
  smoke_args+=(--cli /cli/bin/audiowmark --fixtures /fixtures)
fi
docker run --rm --network host "${mounts[@]}" "$image" sh -ec '
 if command -v apk >/dev/null; then apk add --no-cache python3; else apt-get update && apt-get install -y --no-install-recommends python3; fi
 python3 /smoke.py "$@"' smoke "${smoke_args[@]}"

# A musl CLI must also pass the full smoke suite on glibc Ubuntu, without the
# SDK, repository, builder prefix, or audio-library installations.
if [[ $TARGET == linux-musl-* ]]; then
 ubuntu=$(python3 -c 'import json; print(json.load(open("scripts/release/images.lock.json"))["ubuntu"])')
 docker run --rm --network host \
   -v "$CLI_DIR:/cli:ro" \
   -v "$ROOT/scripts/release/smoke.py:/smoke.py:ro" \
   -v "$ROOT/tests/data:/fixtures:ro" \
   "$ubuntu" sh -ec '
   apt-get update && apt-get install -y --no-install-recommends python3
   python3 /smoke.py --cli /cli/bin/audiowmark --fixtures /fixtures'
fi
