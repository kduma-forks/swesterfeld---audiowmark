#!/usr/bin/env bash
# Mount only the extracted CLI and smoke script: builder libraries are inaccessible.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}"
[[ $TARGET == linux-musl-* ]] || { echo 'container-smoke requires a Linux musl CLI target' >&2; exit 1; }
CLI_DIR="$ROOT/.release/unpacked-cli/$TARGET"
# Run each fully static CLI on both musl and glibc, without audio libraries.
for image_key in alpine ubuntu; do
 image=$(python3 -c 'import json,sys; print(json.load(open("scripts/release/images.lock.json"))[sys.argv[1]])' "$image_key")
 docker run --rm --network host -v "$CLI_DIR:/cli:ro" -v "$ROOT/scripts/release/smoke.py:/smoke.py:ro" "$image" sh -ec '
  if command -v apk >/dev/null; then apk add --no-cache python3; else apt-get update && apt-get install -y --no-install-recommends python3; fi
  python3 /smoke.py --cli /cli/bin/audiowmark'
done
