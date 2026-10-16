#!/usr/bin/env bash
# Native source builds; run within the matching platform/toolchain, never on the host via cross guessing.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?set TARGET}" "${RELEASE_WORK:?set absolute RELEASE_WORK}"
mkdir -p "$RELEASE_WORK"
source "$ROOT/scripts/release/environment.sh"
args=(--cache "${SOURCE_CACHE:-$RELEASE_WORK/downloads}" --sources "$RELEASE_WORK/sources" --licenses "$RELEASE_WORK/licenses")
python3 "$ROOT/scripts/release/sources.py" "${args[@]}"
mkdir -p "$DEPS_PREFIX/lib" "$RELEASE_WORK/build"
common=(--prefix="$DEPS_PREFIX" --libdir="$DEPS_PREFIX/lib" --disable-shared --enable-static --with-pic)
configure_build() {
  local name=$1; shift
  mkdir -p "$RELEASE_WORK/build/$name"
  (cd "$RELEASE_WORK/build/$name"
   "$RELEASE_WORK/sources/$name/configure" "${common[@]}" "$@"
   make -j"$JOBS"
   make install)
}
configure_build libgpg-error --disable-doc --disable-tests --disable-languages --disable-nls
gcrypt_options=()
case "$TARGET" in
  macos-*)
    # Mach-O always prefixes C symbols with _. Libgcrypt's old libtool/nm
    # probe misses Mach-O symbols on current Apple tools and selects the
    # wrong names for its MPI assembly routines unless this is explicit.
    gcrypt_options+=(ac_cv_sys_symbol_underscore=yes)
    ;;
esac
configure_build libgcrypt --disable-doc --with-libgpg-error-prefix="$DEPS_PREFIX" --disable-tests ${gcrypt_options[@]+"${gcrypt_options[@]}"}
configure_build ogg
configure_build vorbis --disable-docs --disable-examples
configure_build flac --disable-programs --disable-examples --disable-docs --disable-cpplibs
configure_build opus --disable-doc --disable-extra-programs
configure_build mpg123 --disable-components --enable-libmpg123 --disable-modules --with-cpu=generic --disable-network
configure_build fftw --enable-float --disable-fortran
# CMake does not consume CPPFLAGS from the environment. Keep the platform
# defines and select direct FLAC symbols when its Windows headers are static.
sndfile_cflags="$CFLAGS $CPPFLAGS"
case "$TARGET" in
  win7-*) sndfile_cflags="$sndfile_cflags -DFLAC__NO_DLL" ;;
esac
cmake -S "$RELEASE_WORK/sources/sndfile" -B "$RELEASE_WORK/build/sndfile" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$DEPS_PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_C_FLAGS="$sndfile_cflags" \
  -DCMAKE_PREFIX_PATH="$DEPS_PREFIX" -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 -DBUILD_SHARED_LIBS=OFF -DBUILD_PROGRAMS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF \
  -DENABLE_EXTERNAL_LIBS=ON -DENABLE_MPEG=OFF -DENABLE_PACKAGE_CONFIG=ON
cmake --build "$RELEASE_WORK/build/sndfile" --parallel "$JOBS"
cmake --install "$RELEASE_WORK/build/sndfile"
make -C "$RELEASE_WORK/sources/zita-resampler/source" -j"$JOBS" \
  CXX="$CXX" AR="$AR" CPPFLAGS="$CPPFLAGS -I. -D_REENTRANT" CXXFLAGS="$CXXFLAGS" \
  PREFIX="$DEPS_PREFIX" LIBDIR="$DEPS_PREFIX/lib" install
# Ensure CMake did not silently skip a format due to missing source-built dependencies.
for name in sndfile libmpg123 fftw3f libgcrypt ogg vorbis vorbisenc flac opus; do
  pkg-config --exists "$name"
done
for name in ogg vorbis vorbisenc FLAC opus; do
  [[ -f "$DEPS_PREFIX/lib/lib$name.a" ]] || { echo "missing static codec $name" >&2; exit 1; }
done
python3 - "$DEPS_PREFIX" "$TARGET" <<'PYCODE'
import pathlib,re,subprocess,sys
libraries=pathlib.Path(sys.argv[1])/'lib'
shared=[p for p in libraries.rglob('*') if p.is_file() and ('.so' in p.name or p.suffix in ('.dylib','.dll'))]
if shared: raise RuntimeError('release dependency prefix contains shared libraries: '+str(shared))
if sys.argv[2].startswith('win7-'):
    symbols=subprocess.check_output(['nm','--undefined-only',str(libraries/'libsndfile.a')],text=True)
    if re.search(r'\b__imp_(?:FLAC__|sf_)\w*',symbols):
        raise RuntimeError('static libsndfile archive references FLAC/sndfile DLL imports')
PYCODE
cp "$ROOT/scripts/release/dependencies.lock.json" "$DEPS_PREFIX/dependencies.lock.json"
