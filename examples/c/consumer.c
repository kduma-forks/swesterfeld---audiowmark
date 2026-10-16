/* GPL-3.0-or-later. Standalone consumer of an extracted audiowmark SDK.
 * Linux: cc -std=c11 -Wall -Wextra -I SDK/include consumer.c -ldl -o consumer
 * macOS: cc -std=c11 -Wall -Wextra -I SDK/include consumer.c -o consumer
 * Windows (MinGW): gcc -std=c11 -Wall -Wextra -I SDK/include consumer.c -o consumer.exe
 * Run: consumer ABS_LIBRARY INPUT.wav OUTPUT.wav
 */
#include "audiowmark.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(_WIN32)
#include <windows.h>
#else
#include <dlfcn.h>
#endif
#define API(ret, name, args) static ret (AUDIOWMARK_CALL *p_##name) args
API(uint32_t, abi_version, (void));
API(const char *, version, (void));
API(void, options_init, (audiowmark_options *));
API(int32_t, context_create, (const audiowmark_options *, audiowmark_context **, audiowmark_error **));
API(void, context_free, (audiowmark_context *));
API(int32_t, context_set_keys, (audiowmark_context *, const audiowmark_key *const *, uint32_t, audiowmark_error **));
API(int32_t, key_generate, (const char *, audiowmark_key **, audiowmark_error **));
API(int32_t, key_import, (const char *, audiowmark_key **, audiowmark_error **));
API(const char *, key_export, (const audiowmark_key *));
API(const char *, key_name, (const audiowmark_key *));
API(void, key_free, (audiowmark_key *));
API(int32_t, add_file, (audiowmark_context *, const char *, const char *, const uint8_t *, audiowmark_error **));
API(int32_t, detect_file, (audiowmark_context *, const char *, audiowmark_result **, audiowmark_error **));
API(int32_t, add_pcm, (audiowmark_context *, const float *, uint64_t, uint32_t, uint32_t, const uint8_t *, float *, uint64_t, audiowmark_error **));
API(int32_t, detect_pcm, (audiowmark_context *, const float *, uint64_t, uint32_t, uint32_t, audiowmark_result **, audiowmark_error **));
API(uint64_t, result_count, (const audiowmark_result *));
API(int32_t, result_get, (const audiowmark_result *, uint64_t, audiowmark_detection *, audiowmark_error **));
API(const char *, result_key_name, (const audiowmark_result *, uint64_t));
API(void, result_free, (audiowmark_result *));
API(int32_t, error_code, (const audiowmark_error *));
API(const char *, error_message, (const audiowmark_error *));
API(void, error_free, (audiowmark_error *));
#if defined(_WIN32)
static HMODULE module;
static void *symbol(const char *name) { return (void *)GetProcAddress(module, name); }
#else
static void *module;
static void *symbol(const char *name) { return dlsym(module, name); }
#endif
#define LOAD(name) do { void *value = symbol("audiowmark_" #name); \
  if (!value) { fprintf(stderr, "missing symbol audiowmark_%s\n", #name); return 1; } \
  memcpy(&p_##name, &value, sizeof(p_##name)); } while (0)
#define REQUIRE(value) do { if (!(value)) { fprintf(stderr, "assertion failed: %s:%d: %s\n", __FILE__, __LINE__, #value); return 1; } } while (0)
static int check(int32_t status, audiowmark_error *error)
{
    if (status != AUDIOWMARK_OK) fprintf(stderr, "native error %d: %s\n", status, error ? p_error_message(error) : "no error handle");
    p_error_free(error); return status == AUDIOWMARK_OK;
}
#define CALL(expr) do { audiowmark_error *e = NULL; int32_t status = (expr); if (!check(status, e)) return 1; } while (0)
static int contains(audiowmark_result *result, const uint8_t payload[16])
{
    int found = 0;
    for (uint64_t i = 0; i < p_result_count(result); ++i)
    {
        audiowmark_detection d;
        audiowmark_error *e = NULL;
        int32_t status = p_result_get(result, i, &d, &e);
        if (!check(status, e)) return 0;
        if (!memcmp(d.payload, payload, 16) && d.key_index == 0 && p_result_key_name(result, i) && d.speed > 0) found = 1;
    }
    return found;
}
int main(int argc, char **argv)
{
    if (argc != 4) { fprintf(stderr, "usage: consumer LIBRARY INPUT.wav OUTPUT.wav\n"); return 2; }
#if defined(_WIN32)
    /* UTF-8 argument to UTF-16 Windows loader. File ABI paths stay UTF-8. */
    int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, argv[1], -1, NULL, 0);
    wchar_t *wide = (wchar_t *)calloc((size_t)n, sizeof(wchar_t));
    REQUIRE(n > 0 && wide);
    REQUIRE(MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, argv[1], -1, wide, n));
    module = LoadLibraryW(wide); free(wide);
#else
    module = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
#endif
    REQUIRE(module);
    LOAD(abi_version); LOAD(version); LOAD(options_init); LOAD(context_create); LOAD(context_free);
    LOAD(context_set_keys); LOAD(key_generate); LOAD(key_import); LOAD(key_export); LOAD(key_name); LOAD(key_free);
    LOAD(add_file); LOAD(detect_file); LOAD(add_pcm); LOAD(detect_pcm);
    LOAD(result_count); LOAD(result_get); LOAD(result_key_name); LOAD(result_free);
    LOAD(error_code); LOAD(error_message); LOAD(error_free);
    REQUIRE(p_abi_version() == AUDIOWMARK_ABI_VERSION);
    REQUIRE(sizeof(audiowmark_options) == 56 && sizeof(audiowmark_detection) == 64);
    printf("C SDK %s\n", p_version());
    audiowmark_options options; p_options_init(&options);
    REQUIRE(options.workers == 1 && options.struct_size == 56 && options.abi_version == 1);
    audiowmark_context *context = NULL;
    CALL(p_context_create(&options, &context, &e));
    const uint8_t payload[16] = {0x01,0x23,0x45,0x67,0x89,0xab,0xcd,0xef,0x01,0x23,0x45,0x67,0x89,0xab,0xcd,0xef};
    audiowmark_key *key = NULL, *imported = NULL;
    CALL(p_key_generate("C consumer", &key, &e));
    CALL(p_key_import(p_key_export(key), &imported, &e));
    REQUIRE(!strcmp(p_key_export(key), p_key_export(imported)));
    REQUIRE(!strcmp(p_key_name(imported), "C consumer"));
    const audiowmark_key *keys[] = {imported};
    CALL(p_context_set_keys(context, keys, 1, &e));
    p_key_free(imported); p_key_free(key);
    audiowmark_result *result = NULL; audiowmark_error *error = NULL;
    REQUIRE(p_detect_file(context, "__missing_audiowmark_file__.wav", &result, &error) == AUDIOWMARK_ERROR_IO);
    REQUIRE(!result && error && p_error_code(error) == AUDIOWMARK_ERROR_IO);
    p_error_free(error); error = NULL;
    CALL(p_add_file(context, argv[2], argv[3], payload, &e));
    CALL(p_detect_file(context, argv[3], &result, &e));
    REQUIRE(contains(result, payload)); p_result_free(result); result = NULL;
    const uint32_t rate = 44100, channels = 1;
    const uint64_t frames = (uint64_t)rate * 40, samples = frames * channels;
    float *input = (float *)malloc((size_t)samples * sizeof(float));
    float *output = (float *)malloc((size_t)samples * sizeof(float)); REQUIRE(input && output);
    uint32_t state = 123456789;
    for (uint64_t i = 0; i < samples; ++i)
    { state ^= state << 13; state ^= state >> 17; state ^= state << 5; input[i] = (float)((double)state / UINT32_MAX * .5 - .25); }
    REQUIRE(p_add_pcm(context, input, frames, channels, rate, payload, output, samples - 1, &error) == AUDIOWMARK_ERROR_ARGUMENT);
    REQUIRE(error && p_error_code(error) == AUDIOWMARK_ERROR_ARGUMENT); p_error_free(error); error = NULL;
    CALL(p_add_pcm(context, input, frames, channels, rate, payload, output, samples, &e));
    CALL(p_detect_pcm(context, output, frames, channels, rate, &result, &e));
    p_context_free(context); /* result is independent of context lifetime */
    REQUIRE(contains(result, payload)); p_result_free(result);
    free(input); free(output);
    printf("C packaged SDK consumer passed (file, PCM, keys, errors, independent results)\n");
    /* Keep module loaded until every owned native handle has been released. */
#if defined(_WIN32)
    FreeLibrary(module);
#else
    dlclose(module);
#endif
    return 0;
}
