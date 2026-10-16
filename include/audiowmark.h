/* audiowmark C ABI v1. GPL-3.0-or-later. */
#ifndef AUDIOWMARK_H
#define AUDIOWMARK_H
#include <stdint.h>
#if defined(_WIN32)
# define AUDIOWMARK_CALL __cdecl
# if defined(AUDIOWMARK_BUILD)
#  define AUDIOWMARK_API __declspec(dllexport)
# elif defined(AUDIOWMARK_STATIC)
#  define AUDIOWMARK_API
# else
#  define AUDIOWMARK_API __declspec(dllimport)
# endif
#else
# define AUDIOWMARK_CALL
# define AUDIOWMARK_API __attribute__((visibility("default")))
#endif
#ifdef __cplusplus
extern "C" {
#endif
#define AUDIOWMARK_ABI_VERSION 1u
#define AUDIOWMARK_PAYLOAD_BYTES 16u
/* All enum values are passed as fixed-width integers, never C enum types. */
#define AUDIOWMARK_OK 0
#define AUDIOWMARK_ERROR_ARGUMENT 1
#define AUDIOWMARK_ERROR_IO 2
#define AUDIOWMARK_ERROR_INTERNAL 3
#define AUDIOWMARK_ERROR_BUSY 4
#define AUDIOWMARK_ERROR_MEMORY 5
#define AUDIOWMARK_SPEED_NONE 0u
#define AUDIOWMARK_SPEED_DETECT 1u
#define AUDIOWMARK_SPEED_PATIENT 2u
#define AUDIOWMARK_SPEED_MANUAL 3u
#define AUDIOWMARK_BLOCK_A 1u
#define AUDIOWMARK_BLOCK_B 2u
#define AUDIOWMARK_BLOCK_AB 3u
#define AUDIOWMARK_BLOCK_ALL 4u
#define AUDIOWMARK_BLOCK_CLIP_A 5u
#define AUDIOWMARK_BLOCK_CLIP_B 6u
#define AUDIOWMARK_BLOCK_CLIP_AB 7u

typedef struct audiowmark_context audiowmark_context;
typedef struct audiowmark_key audiowmark_key;
typedef struct audiowmark_result audiowmark_result;
typedef struct audiowmark_error audiowmark_error;

typedef struct audiowmark_options {
  uint32_t struct_size;
  uint32_t abi_version;
  double strength;              /* CLI --strength units; default 10 */
  double sync_threshold;        /* default .35 */
  double chunk_minutes;         /* default 30 */
  double speed;                 /* manual speed ratio; default 1 */
  uint32_t speed_mode;           /* AUDIOWMARK_SPEED_* */
  uint32_t n_best;               /* default 8 */
  uint32_t workers;              /* default 1; range 1..256 */
  uint32_t reserved;             /* must be zero */
} audiowmark_options;

typedef struct audiowmark_detection {
  uint8_t payload[16];           /* bytes in CLI hex order */
  uint32_t key_index;            /* index in context key list, or 0 for default */
  uint32_t block_type;           /* AUDIOWMARK_BLOCK_* */
  double time_seconds;           /* ALL uses -1 */
  double quality;
  double decode_error;
  double ranking;
  double speed;
} audiowmark_detection;

/* Strings/paths are UTF-8. Calls are synchronous. Independent contexts run in
 * parallel; a context permits one active call (otherwise ERROR_BUSY). Do not
 * destroy any handle while a call uses it. NULL destroy/free is safe.
 * Set error output to NULL on success; on failure it owns a new error if error
 * output was supplied. Free each returned error before reusing its slot.
 * No API call writes host stdout/stderr or changes their modes.
 */
AUDIOWMARK_API uint32_t AUDIOWMARK_CALL audiowmark_abi_version(void);
AUDIOWMARK_API const char * AUDIOWMARK_CALL audiowmark_version(void);
/* ABI1 options is exactly 56 bytes on supported 64-bit targets. This initializer
 * always writes exactly the ABI1 size; future ABI growth needs a new initializer. */
AUDIOWMARK_API void AUDIOWMARK_CALL audiowmark_options_init(audiowmark_options *options);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_context_create(const audiowmark_options *options, audiowmark_context **context, audiowmark_error **error);
AUDIOWMARK_API void AUDIOWMARK_CALL audiowmark_context_free(audiowmark_context *context);
/* Keys are copied into the context; count=0 restores the public CLI default
 * key. Adding uses the first key; detection tries every key. */
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_context_set_keys(audiowmark_context *context, const audiowmark_key *const *keys, uint32_t count, audiowmark_error **error);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_key_generate(const char *name, audiowmark_key **key, audiowmark_error **error);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_key_import(const char *text, audiowmark_key **key, audiowmark_error **error);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_key_load(const char *path, audiowmark_key **key, audiowmark_error **error);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_key_save(const audiowmark_key *key, const char *path, audiowmark_error **error);
/* Borrowed immutable text/name valid until key_free. CLI key file format. */
AUDIOWMARK_API const char * AUDIOWMARK_CALL audiowmark_key_export(const audiowmark_key *key);
AUDIOWMARK_API const char * AUDIOWMARK_CALL audiowmark_key_name(const audiowmark_key *key);
AUDIOWMARK_API void AUDIOWMARK_CALL audiowmark_key_free(audiowmark_key *key);
/* File output is WAV; input uses the native CLI formats (including FLAC/MP3).
 * '-' paths are rejected. Input and output must identify different files. */
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_add_file(audiowmark_context *context, const char *input_path, const char *output_path, const uint8_t payload[16], audiowmark_error **error);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_detect_file(audiowmark_context *context, const char *path, audiowmark_result **result, audiowmark_error **error);
/* Interleaved float32 PCM. frames counts frames, output_samples counts floats.
 * Input must be finite. Channels 1..64, sample_rate 8000..384000. Buffers must
 * not overlap. Output length/rate/channels equal input. Caller owns buffers. */
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_add_pcm(audiowmark_context *context, const float *input, uint64_t frames, uint32_t channels, uint32_t sample_rate, const uint8_t payload[16], float *output, uint64_t output_samples, audiowmark_error **error);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_detect_pcm(audiowmark_context *context, const float *input, uint64_t frames, uint32_t channels, uint32_t sample_rate, audiowmark_result **result, audiowmark_error **error);
/* Results remain valid independently of their originating context. A successful
 * detection with no candidates returns an owned result with count zero. */
AUDIOWMARK_API uint64_t AUDIOWMARK_CALL audiowmark_result_count(const audiowmark_result *result);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_result_get(const audiowmark_result *result, uint64_t index, audiowmark_detection *detection, audiowmark_error **error);
/* Borrowed UTF-8 name valid until result_free; NULL for invalid index. */
AUDIOWMARK_API const char * AUDIOWMARK_CALL audiowmark_result_key_name(const audiowmark_result *result, uint64_t index);
AUDIOWMARK_API void AUDIOWMARK_CALL audiowmark_result_free(audiowmark_result *result);
AUDIOWMARK_API int32_t AUDIOWMARK_CALL audiowmark_error_code(const audiowmark_error *error);
AUDIOWMARK_API const char * AUDIOWMARK_CALL audiowmark_error_message(const audiowmark_error *error);
AUDIOWMARK_API void AUDIOWMARK_CALL audiowmark_error_free(audiowmark_error *error);
#ifdef __cplusplus
}
#endif
#endif
