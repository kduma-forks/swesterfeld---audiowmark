# Format test fixture provenance

The four files in this directory contain the default-key payload
`f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0`. They were generated once from the
same deterministic 40-second, stereo, 44100 Hz, 16-bit noise WAV. The WAV was
watermarked before encoding, so each compressed file exercises input decoding.

The watermarking binary was downloaded from the `native-linux-musl-x86_64`
artifact of successful GitHub Actions run 38918669906. The run HEAD was
`c81503b6f0d1f70dd346c2069d71114f304e66d2`; the downloaded package's embedded
metadata records the earlier commit
`211c71c7e428b9e5467f93e5f3e87d6654fb8e2f`:

```
audiowmark 0.0.0-dev.211c71c7e428
binary size: 8819264 bytes
binary sha256: f6245ac38f3e3e6ed52f5be5f931011289b1db733cfc44e7b2e41d625c2365ad
```

Encoding used Alpine's `ffmpeg-6.1.2-r1` and `ffprobe-6.1.2-r1`, built with
GCC 14.2.0. The external encoder libraries were `lame-libs-3.100-r5`,
`libvorbis-1.3.7-r2`, and `opus-1.5.2-r1`.

The exact generation and encoding commands were:

```sh
AWM=.context/tools/audiowmark-linux-musl-x86_64/bin/audiowmark

"$AWM" --strict test-gen-noise --bits 16 \
  .context/fixture-work/noise.wav 40 44100
"$AWM" --strict add \
  .context/fixture-work/noise.wav .context/fixture-work/marked.wav \
  f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0

sudo install -d .context/images/alpine/fixtures-work
sudo cp .context/fixture-work/marked.wav \
  .context/images/alpine/fixtures-work/marked.wav

sudo chroot .context/images/alpine /usr/bin/ffmpeg \
  -nostdin -hide_banner -loglevel error -y \
  -i /fixtures-work/marked.wav -map 0:a:0 -map_metadata -1 -vn \
  -ar 44100 -ac 2 -c:a flac -compression_level 8 -sample_fmt s16 \
  /fixtures-work/marked.flac
sudo chroot .context/images/alpine /usr/bin/ffmpeg \
  -nostdin -hide_banner -loglevel error -y \
  -i /fixtures-work/marked.wav -map 0:a:0 -map_metadata -1 -vn \
  -ar 44100 -ac 2 -c:a libmp3lame -b:a 320k \
  /fixtures-work/marked.mp3
sudo chroot .context/images/alpine /usr/bin/ffmpeg \
  -nostdin -hide_banner -loglevel error -y \
  -i /fixtures-work/marked.wav -map 0:a:0 -map_metadata -1 -vn \
  -ar 44100 -ac 2 -c:a libvorbis -q:a 8 \
  /fixtures-work/marked.ogg
sudo chroot .context/images/alpine /usr/bin/ffmpeg \
  -nostdin -hide_banner -loglevel error -y \
  -i /fixtures-work/marked.wav -map 0:a:0 -map_metadata -1 -vn \
  -ar 48000 -ac 2 -c:a libopus -b:a 256k -vbr off -application audio \
  /fixtures-work/marked.opus

sudo cp .context/images/alpine/fixtures-work/marked.flac \
  .context/images/alpine/fixtures-work/marked.mp3 \
  .context/images/alpine/fixtures-work/marked.ogg \
  .context/images/alpine/fixtures-work/marked.opus tests/data/
```

Opus supports 48000 Hz rather than 44100 Hz, so FFmpeg resampled that encoded
fixture from the marked 44100 Hz source. The other encoded fixtures remain at
44100 Hz. In particular, `marked.flac` is a real FFmpeg-encoded FLAC file; it
was not produced by naming audiowmark's WAV output with a `.flac` suffix.

Before the fixtures were added, each file was checked with `ffprobe` and with
`audiowmark --strict get`. The probe results and SHA-256 checksums are:

```sh
for file in marked.flac marked.mp3 marked.ogg marked.opus; do
  sudo chroot .context/images/alpine /usr/bin/ffprobe \
    -v error -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels \
    -of default=noprint_wrappers=1 "/fixtures-work/$file"
  "$AWM" --strict get "tests/data/$file"
done
```

The intermediate deterministic source WAV SHA-256 was
`69cbd130b0a176c8f4a9b0c8b7fa127b14d4bbbd3efc32a3602b3a1ac0787a24`;
the marked WAV SHA-256 was
`10e8eb599abdd6b151369c474cc4f5569e58f614d8fe4caa5915fef1fe5d8c2a`.

| file | ffprobe codec | rate/channels | bytes | sha256 |
| --- | --- | --- | ---: | --- |
| `marked.flac` | `flac` | 44100/2 | 7260466 | `da2871f1c33fe0dfa549836d46b1f70a6badcbb9292ce2840450f191a691cfe7` |
| `marked.mp3` | `mp3` | 44100/2 | 1602917 | `722fea26fc1c301ad03bb42e0eb9b2efbf7aa2955a67aa3c033beda639729f80` |
| `marked.ogg` | `vorbis` | 44100/2 | 2207519 | `443b18cefd7ff0016a7911a91adc1892b875b65e7439ebdb330b898c18a4d2d3` |
| `marked.opus` | `opus` | 48000/2 | 1287887 | `1b8c9cc516eb3042e784c1f27b56a9e898ee49c4d2f4ea6dae78af8b1d10dad0` |

For every file, at least one `pattern` line contained the exact payload above.
No exact pattern count is assumed because the decoder can also report weaker
candidate patterns.

The audio source is wholly synthetic output from audiowmark's deterministic
noise generator. It contains no third-party recording or associated recording
rights.
