/* Native C ABI v1. GPL-3.0-or-later. */
#include "audiowmark.h"
#include "wmcommon.hh"
#include "config.h"
#include <mutex>
#include <memory>
#include <limits>
#include <cstring>
#include <cmath>
#include <stdexcept>
#include <sys/stat.h>
#ifdef _WIN32
#include <windows.h>
#endif

struct audiowmark_context {
  EngineConfig config;
  std::vector<Key> keys{Key()};
  std::mutex mutex;
};
struct audiowmark_key { Key key; std::string text; };
struct audiowmark_result { std::vector<EngineDetection> detections; };
struct audiowmark_error { int32_t code; std::string message; };

namespace {
struct Busy : std::exception {};
void require(bool condition, const char *message) {
  if (!condition) throw std::invalid_argument(message);
}
bool valid_utf8(const char *text) {
  const auto *p = reinterpret_cast<const unsigned char *>(text);
  while (*p) {
    uint32_t code = *p++;
    if (code < 128) continue;
    unsigned n; uint32_t minimum;
    if (code >= 0xc2 && code <= 0xdf) { n = 1; code &= 31; minimum = 128; }
    else if (code >= 0xe0 && code <= 0xef) { n = 2; code &= 15; minimum = 2048; }
    else if (code >= 0xf0 && code <= 0xf4) { n = 3; code &= 7; minimum = 65536; }
    else return false;
    while (n--) { if ((*p & 0xc0) != 0x80) return false; code = (code << 6) | (*p++ & 63); }
    if (code < minimum || code > 0x10ffff || (code >= 0xd800 && code <= 0xdfff)) return false;
  }
  return true;
}
void path_check(const char *path) {
  require(path && *path && std::strcmp(path, "-") != 0, "A nonempty file path is required; '-' is not supported");
  require(valid_utf8(path), "Path must be valid UTF-8");
}
void name_check(const char *name) {
  if (!name) return;
  require(valid_utf8(name), "Key name must be valid UTF-8");
  for (const auto *p = reinterpret_cast<const unsigned char *>(name); *p; ++p)
    require(*p >= 32 && *p != 127, "Key name must not contain control characters");
}
int32_t fail(audiowmark_error **out, int32_t code, const char *message) noexcept {
  if (out) {
    try { *out = new audiowmark_error{code, message}; }
    catch (...) { *out = nullptr; }
  }
  return code;
}
template<class F> int32_t boundary(audiowmark_error **out, F&& fn) noexcept {
  if (out) *out = nullptr;
  try {
    EngineConfig quiet; quiet.quiet = true; quiet.workers = 1;
    ConfigScope scope(quiet);
    fn(); return AUDIOWMARK_OK;
  } catch (const Busy&) { return fail(out, AUDIOWMARK_ERROR_BUSY, "Context already has an active operation"); }
  catch (const std::bad_alloc&) { return fail(out, AUDIOWMARK_ERROR_MEMORY, "Memory allocation failed"); }
  catch (const std::invalid_argument& e) { return fail(out, AUDIOWMARK_ERROR_ARGUMENT, e.what()); }
  catch (const EngineError& e) { return fail(out, AUDIOWMARK_ERROR_IO, e.what()); }
  catch (const std::exception& e) { return fail(out, AUDIOWMARK_ERROR_INTERNAL, e.what()); }
  catch (...) { return fail(out, AUDIOWMARK_ERROR_INTERNAL, "Unknown engine exception"); }
}
struct Operation {
  std::unique_lock<std::mutex> lock;
  std::unique_ptr<ConfigScope> scope;
  explicit Operation(audiowmark_context *context) {
    require(context, "Context is required");
    lock = std::unique_lock<std::mutex>(context->mutex, std::try_to_lock);
    if (!lock.owns_lock()) throw Busy();
    scope.reset(new ConfigScope(context->config));
  }
};
size_t pcm_check(const float *input, uint64_t frames, uint32_t channels, uint32_t rate) {
  require(channels >= 1 && channels <= 64, "Channels must be in range 1..64");
  require(rate >= 8000 && rate <= 384000, "Sample rate must be in range 8000..384000");
  require(frames <= uint64_t(std::numeric_limits<size_t>::max() / sizeof(float) / channels), "PCM size overflow");
  const size_t samples = size_t(frames) * channels;
  require(input || !samples, "PCM input is required");
  for (size_t i = 0; i < samples; ++i) require(std::isfinite(input[i]), "PCM samples must be finite");
  return samples;
}
void stream_check(AudioInputStream& stream) {
  require(stream.n_channels() >= 1 && stream.n_channels() <= 64, "Unsupported channel count");
  require(stream.sample_rate() >= 8000 && stream.sample_rate() <= 384000, "Unsupported sample rate");
}
class CheckedInput : public AudioInputStream {
  std::unique_ptr<AudioInputStream> input;
public:
  explicit CheckedInput(std::unique_ptr<AudioInputStream> input) : input(std::move(input)) {}
  int bit_depth() const override { return input->bit_depth(); }
  int sample_rate() const override { return input->sample_rate(); }
  int n_channels() const override { return input->n_channels(); }
  size_t n_frames() const override { return input->n_frames(); }
  Encoding encoding() const override { return input->encoding(); }
  Error read_frames(std::vector<float>& samples, size_t count) override {
    Error err = input->read_frames(samples, count);
    if (!err) for (float sample : samples) require(std::isfinite(sample), "Audio file samples must be finite");
    return err;
  }
};
std::unique_ptr<AudioInputStream> open_input(const char *path) {
  path_check(path);
  Error error;
  auto stream = AudioInputStream::create(path, error);
  if (error || !stream) throw EngineError(error.message());
  stream_check(*stream);
  return std::unique_ptr<AudioInputStream>(new CheckedInput(std::move(stream)));
}
std::string payload_hex(const uint8_t *payload) {
  require(payload, "128-bit payload is required");
  return vec_to_hex_str(std::vector<unsigned char>(payload, payload + 16));
}
bool same_file(const char *a, const char *b) {
  if (std::strcmp(a, b) == 0) return true;
#ifdef _WIN32
  HANDLE ah = CreateFileW(utf8_wide(a).c_str(), 0, FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  HANDLE bh = CreateFileW(utf8_wide(b).c_str(), 0, FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE, nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  BY_HANDLE_FILE_INFORMATION ai{}, bi{};
  bool same = ah != INVALID_HANDLE_VALUE && bh != INVALID_HANDLE_VALUE && GetFileInformationByHandle(ah, &ai) && GetFileInformationByHandle(bh, &bi) && ai.dwVolumeSerialNumber == bi.dwVolumeSerialNumber && ai.nFileIndexHigh == bi.nFileIndexHigh && ai.nFileIndexLow == bi.nFileIndexLow;
  if (ah != INVALID_HANDLE_VALUE) CloseHandle(ah);
  if (bh != INVALID_HANDLE_VALUE) CloseHandle(bh);
  return same;
#else
  struct stat ai{}, bi{};
  return stat(a, &ai) == 0 && stat(b, &bi) == 0 && ai.st_dev == bi.st_dev && ai.st_ino == bi.st_ino;
#endif
}
class PCMInput : public AudioInputStream {
  const float *data;
  size_t frames, position = 0;
  int channels, rate;
public:
  PCMInput(const float *data, size_t frames, int channels, int rate) : data(data), frames(frames), channels(channels), rate(rate) {}
  int bit_depth() const override { return 32; }
  int sample_rate() const override { return rate; }
  int n_channels() const override { return channels; }
  size_t n_frames() const override { return frames; }
  Encoding encoding() const override { return Encoding::FLOAT; }
  Error read_frames(std::vector<float>& output, size_t count) override {
    count = std::min(count, frames - position);
    if (!count) output.clear();
    else output.assign(data + position * channels, data + (position + count) * channels);
    position += count;
    return {};
  }
};
class PCMOutput : public AudioOutputStream {
  int channels, rate;
public:
  std::vector<float> samples;
  PCMOutput(size_t count, int channels, int rate) : channels(channels), rate(rate) { samples.reserve(count); }
  int bit_depth() const override { return 32; }
  int sample_rate() const override { return rate; }
  int n_channels() const override { return channels; }
  Error write_frames(const std::vector<float>& data) override { samples.insert(samples.end(), data.begin(), data.end()); return {}; }
  Error close() override { return {}; }
};
}

uint32_t AUDIOWMARK_CALL audiowmark_abi_version() { return AUDIOWMARK_ABI_VERSION; }
const char * AUDIOWMARK_CALL audiowmark_version() { return VERSION; }
void AUDIOWMARK_CALL audiowmark_options_init(audiowmark_options *options) {
  if (options) *options = audiowmark_options{56, 1, 10, .35, 30, 1, 0, 8, 1, 0};
}
int32_t AUDIOWMARK_CALL audiowmark_context_create(const audiowmark_options *options, audiowmark_context **out, audiowmark_error **error) {
  if (out) *out = nullptr;
  return boundary(error, [&] {
    require(out, "Context output is required");
    audiowmark_options o; audiowmark_options_init(&o);
    if (options) {
      require(options->struct_size >= sizeof(o) && options->abi_version == 1, "Unsupported options size or ABI version");
      o = *options;
    }
    require(o.reserved == 0, "Reserved options field must be zero");
    require(std::isfinite(o.strength) && o.strength > 0 && o.strength <= 1000, "Strength must be in range (0,1000]");
    require(std::isfinite(o.sync_threshold) && o.sync_threshold >= 0 && o.sync_threshold <= 1, "Sync threshold must be in range 0..1");
    require(std::isfinite(o.chunk_minutes) && o.chunk_minutes >= 10 && o.chunk_minutes <= 1440, "Chunk size must be in range 10..1440 minutes");
    require(o.n_best <= 4096 && o.workers >= 1 && o.workers <= 256, "n_best or workers out of range");
    require(o.speed_mode <= 3, "Invalid speed mode");
    require(std::isfinite(o.speed) && o.speed >= .5 && o.speed <= 2, "Speed must be in range .5..2");
    auto context = std::unique_ptr<audiowmark_context>(new audiowmark_context);
    auto& c = context->config;
    c.quiet = true; c.strict = true; c.workers = o.workers;
    c.water_delta = o.strength / 1000.; c.sync_threshold2 = o.sync_threshold;
    c.get_chunk_size = o.chunk_minutes; c.get_n_best = o.n_best;
    c.detect_speed = o.speed_mode == 1; c.detect_speed_patient = o.speed_mode == 2;
    c.try_speed = o.speed_mode == 3 ? o.speed : -1;
    *out = context.release();
  });
}
void AUDIOWMARK_CALL audiowmark_context_free(audiowmark_context *context) { delete context; }
int32_t AUDIOWMARK_CALL audiowmark_context_set_keys(audiowmark_context *context, const audiowmark_key *const *keys, uint32_t count, audiowmark_error **error) {
  return boundary(error, [&] {
    Operation op(context);
    require(count <= 4096 && (keys || count == 0), "Invalid key list");
    std::vector<Key> copy;
    for (uint32_t i = 0; i < count; ++i) { require(keys[i], "Key is required"); copy.push_back(keys[i]->key); }
    if (!count) copy.emplace_back();
    context->keys.swap(copy);
  });
}
int32_t AUDIOWMARK_CALL audiowmark_key_import(const char *text, audiowmark_key **out, audiowmark_error **error) {
  if (out) *out = nullptr;
  return boundary(error, [&] {
    require(out && text, "Key text and output are required");
    require(valid_utf8(text), "Key text must be UTF-8");
    auto key = std::unique_ptr<audiowmark_key>(new audiowmark_key);
    key->key.import_text(text); name_check(key->key.name().c_str()); key->text = key->key.export_text();
    *out = key.release();
  });
}
int32_t AUDIOWMARK_CALL audiowmark_key_generate(const char *name, audiowmark_key **out, audiowmark_error **error) {
  if (out) *out = nullptr;
  return boundary(error, [&] {
    require(out, "Key output is required"); name_check(name);
    Key key; key.import_text("key " + Random::gen_key());
    auto owned = std::unique_ptr<audiowmark_key>(new audiowmark_key);
    std::string text = key.export_text();
    if (name) {
      std::string escaped;
      for (char c : std::string(name)) { if (c == '\\' || c == '"') escaped += '\\'; escaped += c; }
      text += "name \"" + escaped + "\"\n";
    }
    owned->key.import_text(text); owned->text = owned->key.export_text();
    *out = owned.release();
  });
}
int32_t AUDIOWMARK_CALL audiowmark_key_load(const char *path, audiowmark_key **out, audiowmark_error **error) {
  if (out) *out = nullptr;
  return boundary(error, [&] {
    require(out, "Key output is required"); path_check(path);
    auto key = std::unique_ptr<audiowmark_key>(new audiowmark_key);
    key->key.load_key(path); name_check(key->key.name().c_str()); key->text = key->key.export_text();
    *out = key.release();
  });
}
int32_t AUDIOWMARK_CALL audiowmark_key_save(const audiowmark_key *key, const char *path, audiowmark_error **error) {
  return boundary(error, [&] {
    require(key, "Key is required"); path_check(path);
    FILE *f = utf8_fopen(path, "wb"); if (!f) throw EngineError("Cannot open key output");
    size_t count = fwrite(key->text.data(), 1, key->text.size(), f);
    int status = fclose(f);
    if (count != key->text.size() || status) throw EngineError("Cannot write key output");
  });
}
const char * AUDIOWMARK_CALL audiowmark_key_export(const audiowmark_key *key) { return key ? key->text.c_str() : nullptr; }
const char * AUDIOWMARK_CALL audiowmark_key_name(const audiowmark_key *key) { return key ? key->key.name().c_str() : nullptr; }
void AUDIOWMARK_CALL audiowmark_key_free(audiowmark_key *key) { delete key; }
int32_t AUDIOWMARK_CALL audiowmark_add_file(audiowmark_context *context, const char *input, const char *output, const uint8_t payload[16], audiowmark_error **error) {
  return boundary(error, [&] {
    Operation op(context); path_check(input); path_check(output);
    const auto bits = payload_hex(payload);
    require(!same_file(input, output), "Input and output must identify different files");
    auto stream = open_input(input);
    Error err;
    auto out = AudioOutputStream::create(output, stream->n_channels(), stream->sample_rate(), std::max(16, stream->bit_depth()), stream->encoding(), stream->n_frames(), err);
    if (err || !out) throw EngineError(err.message());
    if (add_stream_watermark(context->keys.front(), stream.get(), out.get(), bits, 0)) throw std::runtime_error("Watermark operation failed");
  });
}
int32_t AUDIOWMARK_CALL audiowmark_detect_file(audiowmark_context *context, const char *path, audiowmark_result **out, audiowmark_error **error) {
  if (out) *out = nullptr;
  return boundary(error, [&] {
    Operation op(context); require(out, "Result output is required");
    auto result = std::unique_ptr<audiowmark_result>(new audiowmark_result);
    result->detections = detect_watermark(context->keys, open_input(path));
    *out = result.release();
  });
}
int32_t AUDIOWMARK_CALL audiowmark_add_pcm(audiowmark_context *context, const float *input, uint64_t frames, uint32_t channels, uint32_t rate, const uint8_t payload[16], float *output, uint64_t capacity, audiowmark_error **error) {
  return boundary(error, [&] {
    Operation op(context); const auto bits = payload_hex(payload);
    const size_t count = pcm_check(input, frames, channels, rate);
    require(capacity >= count && (output || !count), "PCM output buffer too small or NULL");
    uintptr_t a = reinterpret_cast<uintptr_t>(input), b = reinterpret_cast<uintptr_t>(output);
    size_t bytes = count * sizeof(float);
    require(!count || (a <= b ? b - a >= bytes : a - b >= bytes), "PCM buffers must not overlap");
    PCMInput in(input, size_t(frames), channels, rate);
    PCMOutput out(count, channels, rate);
    if (add_stream_watermark(context->keys.front(), &in, &out, bits, 0)) throw std::runtime_error("PCM watermark operation failed");
    if (out.samples.size() != count) throw std::runtime_error("PCM output length mismatch");
    if (count) std::memcpy(output, out.samples.data(), bytes);
  });
}
int32_t AUDIOWMARK_CALL audiowmark_detect_pcm(audiowmark_context *context, const float *input, uint64_t frames, uint32_t channels, uint32_t rate, audiowmark_result **out, audiowmark_error **error) {
  if (out) *out = nullptr;
  return boundary(error, [&] {
    Operation op(context); require(out, "Result output is required"); pcm_check(input, frames, channels, rate);
    auto result = std::unique_ptr<audiowmark_result>(new audiowmark_result);
    result->detections = detect_watermark(context->keys, std::unique_ptr<AudioInputStream>(new PCMInput(input, size_t(frames), channels, rate)));
    *out = result.release();
  });
}
uint64_t AUDIOWMARK_CALL audiowmark_result_count(const audiowmark_result *result) { return result ? result->detections.size() : 0; }
int32_t AUDIOWMARK_CALL audiowmark_result_get(const audiowmark_result *result, uint64_t index, audiowmark_detection *out, audiowmark_error **error) {
  return boundary(error, [&] {
    require(result && out && index < result->detections.size(), "Invalid result/index/output");
    const auto& d = result->detections[size_t(index)];
    audiowmark_detection value{};
    require(d.bits.size() == 128, "Unexpected engine payload size");
    for (unsigned i = 0; i < 128; ++i) value.payload[i / 8] |= uint8_t(d.bits[i] != 0) << (7 - i % 8);
    value.key_index = d.key_index; value.block_type = d.block_type;
    value.time_seconds = d.time; value.quality = d.quality; value.decode_error = d.decode_error; value.ranking = d.ranking; value.speed = d.speed;
    *out = value;
  });
}
const char * AUDIOWMARK_CALL audiowmark_result_key_name(const audiowmark_result *result, uint64_t index) { return result && index < result->detections.size() ? result->detections[size_t(index)].key_name.c_str() : nullptr; }
void AUDIOWMARK_CALL audiowmark_result_free(audiowmark_result *result) { delete result; }
int32_t AUDIOWMARK_CALL audiowmark_error_code(const audiowmark_error *error) { return error ? error->code : AUDIOWMARK_OK; }
const char * AUDIOWMARK_CALL audiowmark_error_message(const audiowmark_error *error) { return error ? error->message.c_str() : nullptr; }
void AUDIOWMARK_CALL audiowmark_error_free(audiowmark_error *error) { delete error; }
