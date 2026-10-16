# C SDK consumer

Compile `consumer.c` against the extracted SDK's `include/` directory. The
consumer resolves every ABI function from one explicit native module and releases
native handles in that module. It does not link to build-tree native objects.

```sh
# Linux (glibc or musl)
cc -std=c11 -Wall -Wextra -Werror -I ../../include consumer.c -ldl -o consumer
# macOS: omit -ldl
# Windows: use MinGW gcc and name the output consumer.exe
./consumer /absolute/sdk/lib/libaudiowmark.so input.wav marked.wav
```

Use `audiowmark.dll` on Windows or `libaudiowmark.dylib` on macOS. Give the input
WAV at least 40 seconds of non-silent audio. The consumer checks files, PCM,
key generation/import/export, invalid capacity, errors followed by successful
operations, ABI layouts and results that outlive their context.
