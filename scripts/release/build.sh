#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${RELEASE_WORK:?}" "${VERSION:?}"
source "$ROOT/scripts/release/environment.sh"
[[ -f "$DEPS_PREFIX/dependencies.lock.json" ]] || "$ROOT/scripts/release/build-deps.sh"
# Build a separate source copy: release stamping never changes the checkout.
python3 - "$ROOT" "$RELEASE_WORK/project" "$VERSION" <<'PY'
import pathlib,re,shutil,sys
root,dest,version=map(pathlib.Path,sys.argv[1:])
if dest.exists(): shutil.rmtree(dest)
shutil.copytree(root,dest,ignore=shutil.ignore_patterns('.git','.context','.release','dist','native','target','bin','obj','__pycache__','autom4te.cache'))
p=dest/'configure.ac';text=p.read_text();text,n=re.subn(r'AC_INIT\(\[audiowmark\],\[[^\]]+\]\)',lambda m:'AC_INIT([audiowmark],['+str(version)+'])',text,count=1)
if n!=1: raise RuntimeError('cannot stamp AC_INIT version')
p.write_text(text)
PY
(cd "$RELEASE_WORK/project"; autoreconf -fi)
mkdir -p "$RELEASE_WORK/build/project" "$RELEASE_WORK/install"
export PKG_CONFIG='pkg-config --static'
export AUDIOWMARK_CLI_LDFLAGS=''
case "$TARGET" in
 linux-musl-*)
  export AUDIOWMARK_CLI_LDFLAGS='-all-static'
  ;;
 win7-x86_64)
  export AUDIOWMARK_CLI_LDFLAGS='-all-static'
  ;;
 macos-*) ;;
esac
test_failure() {
 local check_status=$1 log
 for log in src/*.log tests/*.log; do
   [[ -f "$log" ]] || continue
   { printf '\nTest log: %s\n' "$log"; cat "$log"; } >&2 || true
 done
 exit "$check_status"
}
pushd "$RELEASE_WORK/build/project" >/dev/null
 "$RELEASE_WORK/project/configure" --prefix="$RELEASE_WORK/install" --libdir="$RELEASE_WORK/install/lib" \
   --disable-shared --enable-static-deps --disable-videowmark --without-ffmpeg --without-docs
 make -j"$JOBS"
 make check -j"$JOBS" || test_failure $?
 make install
popd >/dev/null
python3 "$ROOT/scripts/release/package.py" --target "$TARGET" --version "$VERSION" \
 --install "$RELEASE_WORK/install" --licenses "$RELEASE_WORK/licenses" \
 --output "${RELEASE_OUTPUT:-$ROOT/dist}" --work "$RELEASE_WORK/packages"
