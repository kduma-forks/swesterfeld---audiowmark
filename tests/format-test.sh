#!/bin/bash

source test-common.sh

SOURCE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd) || die "failed to locate test data"
TMP_BASE=${TMPDIR:-.}
FORMAT_TMP=$(mktemp -d "$TMP_BASE/audiowmark-format-test.XXXXXX") || die "failed to create temporary directory"

cleanup()
{
  rm -rf "$FORMAT_TMP"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

IN_WAV=$FORMAT_TMP/input.wav
MARKED_WAV=$FORMAT_TMP/marked.wav
RAW_WAV=$FORMAT_TMP/raw-roundtrip.wav
RAW_MSG=0123456789abcdef0123456789abcdef

assert_payload()
{
  local audio_file=$1
  local expected=$2
  local output
  shift 2

  output=$(audiowmark get "$@" "$audio_file")
  printf '%s\n' "$output" | \
    awk -v payload="$expected" \
      '$1 == "pattern" && $3 == payload { found = 1 } END { exit !found }' || \
    die "payload $expected not found in '$audio_file'"
}

# WAV input/output and the default key.
audiowmark test-gen-noise --bits 16 "$IN_WAV" 40 44100
audiowmark_add "$IN_WAV" "$MARKED_WAV" "$TEST_MSG"
assert_payload "$MARKED_WAV" "$TEST_MSG"

# Use the clean input so finding TEST_MSG proves that the first RAW add worked.
# Only add accepts the RAW stream options; get reads the final WAV normally.
audiowmark_add "$IN_WAV" - "$TEST_MSG" \
  --output-format raw \
  --raw-rate 44100 --raw-channels 2 --raw-bits 16 \
  --raw-endian little --raw-encoding signed | \
  audiowmark_add --test-key 1 - "$RAW_WAV" "$RAW_MSG" \
    --input-format raw \
    --raw-rate 44100 --raw-channels 2 --raw-bits 16 \
    --raw-endian little --raw-encoding signed

IN_FRAMES=$(audiowmark test-info "$IN_WAV" frames)
RAW_FRAMES=$(audiowmark test-info "$RAW_WAV" frames)
[ -n "$IN_FRAMES" ] || die "input WAV frame count could not be detected"
[ "$IN_FRAMES" = "$RAW_FRAMES" ] || \
  die "RAW round-trip changed frame count ($IN_FRAMES != $RAW_FRAMES)"
assert_payload "$RAW_WAV" "$TEST_MSG"
assert_payload "$RAW_WAV" "$RAW_MSG" --test-key 1

# These are pre-generated from the same deterministic 40-second source. Their
# provenance is recorded in data/README.md; running this test needs no ffmpeg.
for fixture in marked.flac marked.mp3 marked.ogg marked.opus
do
  fixture_path=$SOURCE_DIR/data/$fixture
  [ -r "$fixture_path" ] || die "missing format fixture '$fixture_path'"
  assert_payload "$fixture_path" "$TEST_MSG"
done
