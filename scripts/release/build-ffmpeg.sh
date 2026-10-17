#!/usr/bin/env bash
# Build the full-release-only LAME and FFmpeg dependencies from locked sources.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
: "${TARGET:?set TARGET}" "${RELEASE_WORK:?set absolute RELEASE_WORK}"
source "$ROOT/scripts/release/environment.sh"
[[ "$VARIANT" == full ]] || { echo 'build-ffmpeg.sh requires VARIANT=full' >&2; exit 1; }
for source in lame ffmpeg; do
  [[ -d "$RELEASE_WORK/sources/$source" ]] || { echo "missing prepared source: $source" >&2; exit 1; }
done

mkdir -p "$RELEASE_WORK/build/lame" "$RELEASE_WORK/build/ffmpeg"
(cd "$RELEASE_WORK/build/lame"
 "$RELEASE_WORK/sources/lame/configure" \
   --prefix="$DEPS_PREFIX" --libdir="$DEPS_PREFIX/lib" \
   --disable-shared --enable-static --with-pic --disable-decoder --disable-frontend
 make -j"$JOBS"
 make install)
[[ -f "$DEPS_PREFIX/lib/libmp3lame.a" ]] || { echo 'LAME static archive was not installed' >&2; exit 1; }

thread_options=(--disable-pthreads --disable-w32threads)
case "$TARGET" in
  win7-*) thread_options=(--disable-pthreads --enable-w32threads) ;;
  linux-*|macos-*) thread_options=(--enable-pthreads --disable-w32threads) ;;
esac
ffmpeg_ldflags="$LDFLAGS"
case "$TARGET" in
  linux-*|win7-*) ffmpeg_ldflags="$ffmpeg_ldflags -static" ;;
esac

(cd "$RELEASE_WORK/build/ffmpeg"
 "$RELEASE_WORK/sources/ffmpeg/configure" \
   --prefix="$DEPS_PREFIX" --libdir="$DEPS_PREFIX/lib" \
   --cc="$CC" --cxx="$CXX" --ar="$AR" --ranlib="$RANLIB" --strip="$STRIP" \
   --disable-shared --enable-static --enable-pic \
   --disable-autodetect --disable-network --disable-hwaccels \
   --disable-avdevice --disable-indevs --disable-outdevs \
   --disable-ffplay --disable-doc --disable-debug --disable-iconv \
   --enable-ffmpeg --enable-ffprobe \
   --enable-libmp3lame --enable-libopus --enable-libvorbis \
   --pkg-config-flags=--static \
   --extra-cflags="$CFLAGS $CPPFLAGS" --extra-ldflags="$ffmpeg_ldflags" \
   "${thread_options[@]}"

 config=ffbuild/config.mak
 required=(
   FFMPEG FFPROBE AAC_ENCODER LIBMP3LAME_ENCODER LIBOPUS_ENCODER LIBVORBIS_ENCODER FLAC_ENCODER
   AAC_DECODER MP3_DECODER OPUS_DECODER VORBIS_DECODER FLAC_DECODER
   HLS_DEMUXER HLS_MUXER WAV_DEMUXER WAV_MUXER MPEGTS_DEMUXER MPEGTS_MUXER
   MOV_DEMUXER MOV_MUXER MATROSKA_DEMUXER MATROSKA_MUXER WEBM_MUXER
   AVI_DEMUXER AVI_MUXER OGG_DEMUXER OGG_MUXER
 )
 pcm=(S8 U8 S16LE S24LE S32LE U16LE U24LE U32LE F32LE F64LE S16BE S24BE S32BE U16BE U24BE U32BE F32BE F64BE)
 for component in "${pcm[@]}"; do
   required+=("PCM_${component}_ENCODER" "PCM_${component}_DECODER" "PCM_${component}_MUXER" "PCM_${component}_DEMUXER")
 done
 for component in "${required[@]}"; do
   grep -qx "CONFIG_${component}=yes" "$config" || { echo "FFmpeg required component is disabled: $component" >&2; exit 1; }
 done
 case "$TARGET" in
   win7-*) grep -qx 'HAVE_W32THREADS=yes' "$config" || { echo 'FFmpeg w32threads support is disabled' >&2; exit 1; } ;;
   *) grep -qx 'HAVE_PTHREADS=yes' "$config" || { echo 'FFmpeg pthread support is disabled' >&2; exit 1; } ;;
 esac
 make -j"$JOBS"
 make install)

exe_suffix=
[[ "$TARGET" == win7-* ]] && exe_suffix=.exe
for program in ffmpeg ffprobe; do
  executable="$DEPS_PREFIX/bin/$program$exe_suffix"
  [[ -x "$executable" ]] || { echo "missing installed FFmpeg program: $executable" >&2; exit 1; }
done
ffmpeg_exe="$DEPS_PREFIX/bin/ffmpeg$exe_suffix"
ffprobe_exe="$DEPS_PREFIX/bin/ffprobe$exe_suffix"
"$ffmpeg_exe" -hide_banner -buildconf > "$RELEASE_WORK/ffmpeg-buildconf.txt"
"$ffprobe_exe" -hide_banner -version > "$RELEASE_WORK/ffprobe-version.txt"

# Check the installed programs too: this detects a wrong executable or install
# independently of configure's component report.
encoders=$("$ffmpeg_exe" -hide_banner -encoders 2>/dev/null)
decoders=$("$ffmpeg_exe" -hide_banner -decoders 2>/dev/null)
formats=$("$ffmpeg_exe" -hide_banner -formats 2>/dev/null)
for encoder in aac libmp3lame libopus libvorbis flac; do
  grep -Eq "^[[:space:]]*A[A-Z.]{5}[[:space:]]+$encoder([[:space:]]|$)" <<<"$encoders" || {
    echo "installed FFmpeg is missing encoder: $encoder" >&2; exit 1;
  }
done
for decoder in aac mp3 opus vorbis flac; do
  grep -Eq "^[[:space:]]*A[A-Z.]{5}[[:space:]]+$decoder([[:space:]]|$)" <<<"$decoders" || {
    echo "installed FFmpeg is missing decoder: $decoder" >&2; exit 1;
  }
done
for format in hls mov mp4 matroska webm avi mpegts wav ogg; do
  grep -Eq "^[[:space:]DE.]+[[:space:]]+([^[:space:]]*,)*$format(,|[[:space:]])" <<<"$formats" || {
    echo "installed FFmpeg is missing format: $format" >&2; exit 1;
  }
done

# No dependency build may leave a redistributable shared library in the prefix.
python3 - "$DEPS_PREFIX" <<'PY'
import pathlib,sys
prefix=pathlib.Path(sys.argv[1])
shared=[p for p in prefix.rglob('*') if p.is_file() and ('.so' in p.name or p.suffix in ('.dylib','.dll'))]
if shared: raise RuntimeError('full dependency prefix contains shared libraries: '+str(shared))
PY
