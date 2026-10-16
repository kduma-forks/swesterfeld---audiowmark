#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?}" "${RELEASE_WORK:?}" "${VERSION:?}"
source "$ROOT/scripts/release/environment.sh"
case "$VARIANT:$TARGET" in
  full:win7-x86_64|full:linux-musl-x86_64|full:linux-musl-aarch64|full:macos-x86_64|full:macos-aarch64) ;;
  full:*) echo "full releases do not support target: $TARGET" >&2; exit 1 ;;
  *) ;;
esac
if ! python3 - "$ROOT/scripts/release" "$DEPS_PREFIX/dependencies.lock.json" "$VARIANT" <<'PY'
import json,pathlib,sys
sys.path.insert(0,sys.argv[1])
from sources import effective_manifest
sentinel=pathlib.Path(sys.argv[2])
if not sentinel.is_file() or json.loads(sentinel.read_text()) != effective_manifest(sys.argv[3]):
    raise SystemExit(1)
PY
then
  "$ROOT/scripts/release/build-deps.sh"
fi
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
export AUDIOWMARK_CLI_LDFLAGS='' AUDIOWMARK_SHARED_LDFLAGS=''
case "$TARGET" in
 linux-musl-*)
  export AUDIOWMARK_CLI_LDFLAGS='-all-static'
  export AUDIOWMARK_SHARED_LDFLAGS='-static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL'
  ;;
 linux-gnu-*)
  export AUDIOWMARK_CLI_LDFLAGS='-static-libstdc++ -static-libgcc'
  export AUDIOWMARK_SHARED_LDFLAGS='-static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL'
  ;;
 win7-x86_64)
  export AUDIOWMARK_CLI_LDFLAGS='-all-static'
  export AUDIOWMARK_SHARED_LDFLAGS='-static-libstdc++ -static-libgcc -Wl,--exclude-libs,ALL'
  ;;
 macos-*) ;;
esac
# Expand optional arrays with ${array[@]+"${array[@]}"}: macOS Bash 3.2
# otherwise treats an empty array as unset under set -u.
additional=()
case "${SANITIZER:-}" in
 "") ;;
 asan-ubsan) additional=(--enable-asan --enable-ubsan) ;;
 tsan) additional=(--enable-tsan) ;;
 *) echo 'unknown SANITIZER' >&2; exit 1 ;;
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
 configure_options=(--enable-static-deps --without-docs)
 if [[ "$VARIANT" == full ]]; then
   configure_options+=(--disable-shared --enable-videowmark --with-ffmpeg --enable-bundled-tools)
 else
   configure_options+=(--enable-shared --disable-videowmark --without-ffmpeg --disable-bundled-tools)
 fi
 "$RELEASE_WORK/project/configure" --prefix="$RELEASE_WORK/install" --libdir="$RELEASE_WORK/install/lib" \
   "${configure_options[@]}" ${additional[@]+"${additional[@]}"}
 make -j"$JOBS"
 if [[ "$VARIANT" == full ]]; then
   exe_suffix=
   [[ "$TARGET" == win7-* ]] && exe_suffix=.exe
   # Bundled mode resolves helpers beside the running test binary. Put the
   # exact dependency build there before make check, then in install/bin.
   for program in ffmpeg ffprobe; do
     cp "$DEPS_PREFIX/bin/$program$exe_suffix" "src/$program$exe_suffix"
     chmod +x "src/$program$exe_suffix"
   done
 fi
 if [[ -n "${SANITIZER:-}" ]]; then
   make -C src check -j"$JOBS" || test_failure $?
   (cd src && ./testthreadpool) || test_failure $?
 else
   make check -j"$JOBS" || test_failure $?
 fi
 make install
 if [[ "$VARIANT" == full ]]; then
   for program in ffmpeg ffprobe; do
     cp "$DEPS_PREFIX/bin/$program$exe_suffix" "$RELEASE_WORK/install/bin/$program$exe_suffix"
     chmod +x "$RELEASE_WORK/install/bin/$program$exe_suffix"
   done
 fi
popd >/dev/null
if [[ "${VALIDATION_ONLY:-0}" == 1 ]]; then exit 0; fi
python3 "$ROOT/scripts/release/package.py" --target "$TARGET" --version "$VERSION" \
 --install "$RELEASE_WORK/install" --licenses "$RELEASE_WORK/licenses" \
 --output "${RELEASE_OUTPUT:-$ROOT/dist}" --work "$RELEASE_WORK/packages" --variant "$VARIANT"
