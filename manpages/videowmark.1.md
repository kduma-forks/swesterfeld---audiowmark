% VIDEOWMARK(1) videowmark | User Commands

# NAME

videowmark — video watermarking tool (using audio track)

# SYNOPSIS

**videowmark** [*options*] *command* [*args...*]

# DESCRIPTION

**videowmark** creates watermarked video files containing an embedded message,
and can retrieve an embedded message from a previously watermarked video.

Messages are provided as hexadecimal data and embedded in the audio track of
the video, intended to be robust against common audio processing operations.

**videowmark** is a native program. It needs no shell, Bash or Python at run
time. It runs **ffmpeg** and **ffprobe** to read and write media, and
**audiowmark** to embed and detect the watermark (see *TOOLS*).

# COMMANDS

**add** *input_video* *watermarked_video* *message_hex*

: Create a watermarked video file containing the provided message. The video
stream is copied without recompression. The audio stream is watermarked and
encoded again with the same codec (see *AUDIO CODECS*).

**get** *watermarked_video*

: Retrieve the embedded message from a watermarked video. The report of
**audiowmark get** is printed to standard output: one *pattern* line per
detected message, with its time position, the detected hexadecimal message and
detection values.

**probe** *input_video*

: Print the input path followed by a short codec and bit rate summary in
encoder-option style, for example ` -c:a mp3 -ab 128000`. This is the legacy
summary kept from earlier releases. It is not the exact encoder selection that
**add** makes; for example, **add** encodes MP3 with **libmp3lame** and Vorbis
with **libvorbis**. Only stream information is read; no media file is written.

# GLOBAL OPTIONS

These options apply to all commands.

**\--strength** *s*

: Set watermark strength. The value is passed to **audiowmark**.

**\--key** *file*

: Load watermarking key material from *file*. The value is passed to
**audiowmark**.

**-q**, **\--quiet**

: Disable informational messages.

**-v**, **\--verbose**

: Enable verbose output from the underlying **ffmpeg** processing.

**-h**, **\--help**

: Print a short usage summary and exit.

# ARGUMENTS

*input_video*

:   Path to the input (unwatermarked) video file. It must contain exactly one
    audio stream and exactly one video stream.

*watermarked_video*

:   Path to the output (watermarked) video file (for **add**), or the input
    watermarked video file (for **get**).

*message_hex*

:   Message to embed, provided as hexadecimal digits. The default watermark
    payload is 128 bits. Use 32 hexadecimal digits for the full 128-bit payload,
    for example `0123456789abcdef0011223344556677`. A shorter message is
    repeated to fill the payload, for compatibility with earlier releases.
    Messages longer than 32 hexadecimal digits are rejected.

# AUDIO CODECS

**add** keeps the codec of the input audio stream. The supported codecs and the
encoders they are written with are:

| input codec     | encoder            |
|-----------------|--------------------|
| aac             | aac                |
| mp3             | libmp3lame         |
| opus            | libopus            |
| vorbis          | libvorbis          |
| flac            | flac               |
| pcm\_\*          | the same PCM codec |

An input with any other audio codec is rejected before any work starts. There
is no automatic conversion to another codec.

# OUTPUT FILES

The input and output extensions must match, and input and output must be
different files.

The output is written to a temporary file in the same directory and renamed
over *watermarked_video* only after it is complete. If processing fails, an
existing output file is left unchanged.

# TOOLS

**videowmark** looks for **ffmpeg**, **ffprobe** and **audiowmark** beside its
own executable first, then on the search path. In the bundled release packages
the sibling programs are required, and the search path is not used.

# EXIT STATUS

**0**

:   The operation completed successfully.

**>0**

:   An error occurred. Messages are printed to standard error.

# EXAMPLES

Show the legacy codec and bit rate summary for a file:

`videowmark probe input.mp4`

Embed a 32-digit hexadecimal message into a video:

`videowmark add input.mp4 output.mp4 0123456789abcdef0011223344556677`

Retrieve the message from a watermarked video:

`videowmark get output.mp4`

# SEE ALSO

- **ffmpeg**(1)
- **ffprobe**(1)
- **audiowmark**(1)

# HOMEPAGE

https://uplex.de/audiowmark/

# AUTHOR

**videowmark** is part of the audiowmark project and was written by
Stefan Westerfeld <stefan@space.twc.de>.

# COPYRIGHT

Copyright © 2018–2020 Stefan Westerfeld <stefan@space.twc.de>.
Licensed under the GNU General Public License, version 3 or later.
