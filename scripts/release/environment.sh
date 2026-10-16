#!/usr/bin/env bash
# Source this file after setting TARGET and RELEASE_WORK. No host audio libraries.
set -euo pipefail
: "${TARGET:?set release target}"
: "${RELEASE_WORK:?set absolute work directory}"
export VARIANT="${VARIANT:-cli}"
case "$VARIANT" in
  cli|full) ;;
  *) echo "unknown release variant: $VARIANT (expected cli or full)" >&2; return 1 ;;
esac
export DEPS_PREFIX="$RELEASE_WORK/prefix"
export PATH="$DEPS_PREFIX/bin:$PATH"
export PKG_CONFIG_LIBDIR="$DEPS_PREFIX/lib/pkgconfig:$DEPS_PREFIX/share/pkgconfig"
export PKG_CONFIG_PATH="$PKG_CONFIG_LIBDIR"
export CFLAGS="-O2 -fPIC -fvisibility=hidden"
export CXXFLAGS="-O2 -fPIC -fvisibility=hidden -fvisibility-inlines-hidden"
export CPPFLAGS="-I$DEPS_PREFIX/include"
export LDFLAGS="-L$DEPS_PREFIX/lib"
export CC="${CC:-gcc}" CXX="${CXX:-g++}" AR="${AR:-ar}" RANLIB="${RANLIB:-ranlib}"
export STRIP="${STRIP:-strip}"
case "$TARGET" in
  win7-x86_64)
    [[ "${MSYSTEM:-}" == MINGW64 ]] || { echo 'Windows releases require MINGW64/MSVCRT, never UCRT' >&2; return 1; }
    export CPPFLAGS="$CPPFLAGS -D_WIN32_WINNT=0x0601 -DWINVER=0x0601 -D__USE_MINGW_ANSI_STDIO=1"
    export CFLAGS="$CFLAGS -mms-bitfields" CXXFLAGS="$CXXFLAGS -mms-bitfields"
    ;;
  macos-*)
    export MACOSX_DEPLOYMENT_TARGET=15.0 CC=clang
    export CXX=clang++
    ;;
  linux-musl-*) ;;
  *) echo "unknown target: $TARGET" >&2; return 1 ;;
esac
actual_arch=$(uname -m)
case "$TARGET:$actual_arch" in
  *-x86_64:x86_64|*-aarch64:aarch64|macos-aarch64:arm64) ;;
  *) echo "release target $TARGET disagrees with native host $actual_arch" >&2; return 1 ;;
esac
export JOBS="${JOBS:-4}"
