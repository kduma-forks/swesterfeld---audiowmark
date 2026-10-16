#!/usr/bin/env bash
# Mount only extracted packages and test inputs: builder libraries are inaccessible.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}"
export VARIANT="${VARIANT:-cli}"
[[ $VARIANT == cli || $VARIANT == full ]] || { echo 'VARIANT must be cli or full' >&2; exit 1; }
case "$TARGET" in
 linux-musl-*) image_keys=(alpine ubuntu) ;;
 linux-gnu-*)
   [[ $VARIANT == cli ]] || { echo 'GNU targets only build the SDK in the cli variant' >&2; exit 1; }
   image_keys=(ubuntu) ;;
 *) echo 'container-smoke is only for Linux' >&2; exit 1 ;;
esac
SDK_DIR="$ROOT/.release/native/$TARGET"
CLI_DIR="$ROOT/.release/unpacked-$VARIANT/$TARGET"
for image_key in "${image_keys[@]}"; do
 image=$(python3 -c 'import json,sys; print(json.load(open("scripts/release/images.lock.json"))[sys.argv[1]])' "$image_key")
 mounts=(-v "$ROOT/scripts/release/smoke.py:/smoke.py:ro")
 smoke_args=(--variant "$VARIANT")
 # A musl SDK is loadable on Alpine; only its static CLI is exercised on Ubuntu.
 if [[ $VARIANT == cli && ( $TARGET == linux-gnu-* || $image_key == alpine ) ]]; then
   mounts+=(-v "$SDK_DIR:/sdk:ro")
   smoke_args+=(--sdk /sdk)
 fi
 if [[ $TARGET == linux-musl-* ]]; then
   mounts+=(-v "$CLI_DIR:/cli:ro" -v "$ROOT/tests/data:/data:ro")
   smoke_args+=(--cli /cli/bin/audiowmark --fixtures /data)
   if [[ $VARIANT == full ]]; then
     mounts+=(-v "$ROOT/tests/full-test.py:/full-test.py:ro" -v "$ROOT/tests/fixtures:/fixtures:ro")
     smoke_args+=(--full-tests /full-test.py)
   fi
 fi
 docker run --rm --network host "${mounts[@]}" "$image" sh -ec '
  if command -v apk >/dev/null; then apk add --no-cache python3; else apt-get update && apt-get install -y --no-install-recommends python3; fi
  python3 /smoke.py "$@"' smoke "${smoke_args[@]}"
done
