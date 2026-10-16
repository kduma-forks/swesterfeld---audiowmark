/* Native ABI regression: real payload128 PCM/file/CLI operations and concurrency. */
#include "audiowmark.h"
#include "wavdata.hh"
#include "wmcommon.hh"
#include "sfoutputstream.hh"
#include <future>
#include <iostream>
#include <random>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <atomic>
#include <set>
#include <sys/stat.h>
#include <unistd.h>
#ifdef _WIN32
#include <direct.h>
#endif

static_assert(sizeof(audiowmark_options) == 56, "options layout");
static_assert(sizeof(audiowmark_detection) == 64, "detection layout");
static void check(bool condition, const char *message) { if (!condition) throw std::runtime_error(message); }
struct TestDirectory {
  std::string path;
  explicit TestDirectory(const std::string& p) : path(p) {
#ifdef _WIN32
    check(_mkdir(path.c_str()) == 0, "fixture directory");
#else
    check(mkdir(path.c_str(), 0700) == 0, "fixture directory");
#endif
  }
  ~TestDirectory() {
    for (const auto *name : {u8"źródło.wav", "wynik.wav", "invalid-float.wav", "invalid-out.wav",
                             "alias.wav", "in.wav", "out.wav", "cli.log", u8"klucz-Łódź.key", "cli.key"}) {
      const auto file = path + "/" + name;
#ifdef _WIN32
      _wremove(utf8_wide(file).c_str());
#else
      std::remove(file.c_str());
#endif
    }
#ifdef _WIN32
    _rmdir(path.c_str());
#else
    rmdir(path.c_str());
#endif
  }
};
struct Context {
  audiowmark_context *p = nullptr;
  explicit Context(audiowmark_options *options = nullptr) { check(audiowmark_context_create(options, &p, nullptr) == 0, "context create"); }
  ~Context() { audiowmark_context_free(p); }
};
struct Result {
  audiowmark_result *p = nullptr;
  ~Result() { audiowmark_result_free(p); }
};
struct KeyHandle {
  audiowmark_key *p = nullptr;
  KeyHandle() = default;
  explicit KeyHandle(const char *text) { check(audiowmark_key_import(text, &p, nullptr) == 0, "key import"); }
  ~KeyHandle() { audiowmark_key_free(p); }
};
static bool contains(const Result& result, const uint8_t *payload, uint32_t key_index = 0) {
  for (uint64_t i = 0; i < audiowmark_result_count(result.p); ++i) {
    audiowmark_detection d{};
    check(audiowmark_result_get(result.p, i, &d, nullptr) == 0, "result accessor");
    check(std::isfinite(d.quality) && std::isfinite(d.decode_error) && std::isfinite(d.ranking) && std::isfinite(d.speed), "finite result fields");
    check(d.block_type >= 1 && d.block_type <= 7, "block type");
    check(audiowmark_result_key_name(result.p, i), "result name");
    if (!std::memcmp(d.payload, payload, 16) && d.key_index == key_index) return true;
  }
  return false;
}
static std::vector<float> signal(unsigned rate, unsigned channels, unsigned seconds) {
  std::mt19937 random(12345);
  std::vector<float> values(size_t(rate) * channels * seconds);
  for (auto& v : values) v = (double(random()) / random.max() - .5) * .7;
  return values;
}
static void errors() {
  audiowmark_options options; audiowmark_options_init(&options);
  check(options.workers == 1 && options.strength == 10 && options.abi_version == 1, "defaults");
  options.n_best = 0;
  { Context threshold_only(&options); }
  options.chunk_minutes = 2;
  audiowmark_context *too_small = nullptr;
  check(audiowmark_context_create(&options, &too_small, nullptr) == AUDIOWMARK_ERROR_ARGUMENT && !too_small, "unsafe chunk size rejected");
  options.chunk_minutes = 30;
  options.struct_size = 8;
  audiowmark_context *invalid = reinterpret_cast<audiowmark_context *>(uintptr_t(1));
  audiowmark_error *error = nullptr;
  check(audiowmark_context_create(&options, &invalid, &error) == AUDIOWMARK_ERROR_ARGUMENT && !invalid, "invalid options");
  check(audiowmark_error_code(error) == AUDIOWMARK_ERROR_ARGUMENT && audiowmark_error_message(error), "structured error");
  audiowmark_error_free(error); error = nullptr;
  Context context;
  Result result;
  check(audiowmark_detect_file(context.p, "missing-audiowmark-test-file", &result.p, &error) == AUDIOWMARK_ERROR_IO && !result.p, "missing input");
  audiowmark_error_free(error); error = nullptr;
  check(audiowmark_detect_file(context.p, "-", &result.p, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "stdin rejection");
  check(audiowmark_detect_file(context.p, "\xff", &result.p, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "invalid UTF-8");
  check(audiowmark_detect_pcm(context.p, nullptr, 1, 2, 44100, &result.p, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "null PCM");
  check(audiowmark_detect_pcm(context.p, nullptr, UINT64_MAX, 64, 44100, &result.p, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "overflow PCM");
  float nan = std::numeric_limits<float>::quiet_NaN();
  check(audiowmark_detect_pcm(context.p, &nan, 1, 1, 44100, &result.p, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "nonfinite PCM");
  check(audiowmark_detect_pcm(context.p, nullptr, 0, 1, 44100, &result.p, &error) == 0 && result.p && !error && audiowmark_result_count(result.p) == 0, "empty success after errors");
  audiowmark_detection detection{};
  check(audiowmark_result_get(result.p, 0, &detection, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "bounds result");
  audiowmark_key *key = nullptr;
  check(audiowmark_key_import("key deadbeef", &key, nullptr) == AUDIOWMARK_ERROR_ARGUMENT && !key, "bad key");
  check(audiowmark_key_generate("bad\nname", &key, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "key controls");
  audiowmark_context_free(nullptr); audiowmark_result_free(nullptr); audiowmark_key_free(nullptr); audiowmark_error_free(nullptr);
}
static void keys() {
  std::vector<std::future<std::vector<std::string>>> tasks;
  for (unsigned worker = 0; worker < 4; ++worker) {
    tasks.push_back(std::async(std::launch::async, [] {
      std::vector<std::string> texts;
      for (unsigned n = 0; n < 16; ++n) {
        KeyHandle generated, copy;
        check(audiowmark_key_generate(u8"generated-Łódź", &generated.p, nullptr) == 0, "key generation");
        const std::string text = audiowmark_key_export(generated.p);
        check(audiowmark_key_import(text.c_str(), &copy.p, nullptr) == 0, "generated key import");
        audiowmark_key_free(generated.p); generated.p = nullptr;
        check(text == audiowmark_key_export(copy.p), "key export identity and independent lifetime");
        texts.push_back(text);
      }
      return texts;
    }));
  }
  std::set<std::string> distinct;
  for (auto& task : tasks)
    for (const auto& text : task.get())
      check(distinct.insert(text).second, "fresh independent random keys");
  check(distinct.size() == 64, "all parallel keys generated");
}
static const uint8_t payload_a[16] = {0x01,0x23,0x45,0x67,0x89,0xab,0xcd,0xef,0xfe,0xdc,0xba,0x98,0x76,0x54,0x32,0x10};
static const uint8_t payload_b[16] = {0xde,0xad,0xbe,0xef,0xc0,0xff,0xee,0x12,0xab,0xcd,0x98,0x76,0x54,0x32,0x10,0xff};
static void pcm_formats() {
  Context context;
  for (const auto& format : {std::pair<unsigned,unsigned>{44100,1}, {48000,2}, {32000,1}}) {
    auto input = signal(format.first, format.second, 60);
    std::vector<float> output(input.size());
    check(audiowmark_add_pcm(context.p, input.data(), input.size()/format.second, format.second, format.first, payload_a, output.data(), output.size()-1, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "small output");
    check(audiowmark_add_pcm(context.p, input.data(), input.size()/format.second, format.second, format.first, payload_a, input.data(), input.size(), nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "overlap output");
    check(audiowmark_add_pcm(context.p, input.data(), input.size()/format.second, format.second, format.first, payload_a, output.data(), output.size(), nullptr) == 0, "PCM add");
    check(input != output, "PCM must change");
    Result result;
    check(audiowmark_detect_pcm(context.p, output.data(), output.size()/format.second, format.second, format.first, &result.p, nullptr) == 0, "PCM detect");
    check(contains(result, payload_a), "PCM roundtrip payload");
  }
  auto silence = std::vector<float>(44100 * 4, 0);
  Result empty;
  check(audiowmark_detect_pcm(context.p, silence.data(), silence.size(), 1, 44100, &empty.p, nullptr) == 0 && audiowmark_result_count(empty.p) == 0, "silence has no candidates");
}
static void concurrency() {
  audiowmark_options a, b; audiowmark_options_init(&a); audiowmark_options_init(&b);
  a.workers = 1; a.strength = 12; b.workers = 2; b.strength = 30;
  Context ca(&a), cb(&b);
  KeyHandle ka("key 0123456789abcdef0123456789abcdef\nname \"one\"\n");
  KeyHandle kb("key fedcba9876543210fedcba9876543210\nname \"two\"\n");
  const audiowmark_key *ak[] = {ka.p}, *bk[] = {kb.p};
  check(audiowmark_context_set_keys(ca.p, ak, 1, nullptr) == 0 && audiowmark_context_set_keys(cb.p, bk, 1, nullptr) == 0, "set independent keys");
  auto input = signal(44100, 1, 60);
  std::vector<float> oa(input.size()), ob(input.size());
  std::promise<void> start; auto ready = start.get_future().share();
  auto run = [&](Context& c, std::vector<float>& output, const uint8_t *payload) {
    ready.wait();
    check(audiowmark_add_pcm(c.p, input.data(), input.size(), 1, 44100, payload, output.data(), output.size(), nullptr) == 0, "parallel add");
    Result result;
    check(audiowmark_detect_pcm(c.p, output.data(), output.size(), 1, 44100, &result.p, nullptr) == 0 && contains(result, payload), "parallel detect isolated config");
  };
  auto fa = std::async(std::launch::async, [&] { run(ca, oa, payload_a); });
  auto fb = std::async(std::launch::async, [&] { run(cb, ob, payload_b); });
  start.set_value(); fa.get(); fb.get();
  check(oa != ob, "distinct keys/strength outputs");
  const audiowmark_key *both[] = {kb.p, ka.p};
  check(audiowmark_context_set_keys(ca.p, both, 2, nullptr) == 0, "multi-key set");
  Result multi;
  check(audiowmark_detect_pcm(ca.p, oa.data(), oa.size(), 1, 44100, &multi.p, nullptr) == 0 && contains(multi, payload_a, 1), "key index lookup");
  check(!contains(multi, payload_a, 0), "wrong key must not decode payload");
  // Deterministic same-context busy check: repeat while a long operation runs.
  std::atomic<bool> done{false};
  auto operation = std::async(std::launch::async, [&] {
    try {
      int status;
      do { status = audiowmark_add_pcm(ca.p, input.data(), input.size(), 1, 44100, payload_a, oa.data(), oa.size(), nullptr); } while (status == AUDIOWMARK_ERROR_BUSY);
      check(status == 0, "busy primary add");
      done = true;
    } catch (...) { done = true; throw; }
  });
  bool busy = false;
  while (!done) {
    if (audiowmark_context_set_keys(ca.p, nullptr, 0, nullptr) == AUDIOWMARK_ERROR_BUSY) { busy = true; break; }
    std::this_thread::yield();
  }
  operation.get(); check(busy, "same context busy");
}
static void files_cli() {
  const std::string prefix = "testapi-" + std::to_string(getpid());
  TestDirectory fixtures(prefix);
  const std::string input = prefix + u8"/źródło.wav", output = prefix + u8"/wynik.wav";
  auto values = signal(44100, 2, 60);
  WavData wav(values, 2, 44100, 24); check(!wav.save(input), "write Unicode WAV");
  const std::string invalid_path = prefix + "/invalid-float.wav";
  { SFOutputStream bad;
    check(!bad.open(invalid_path, 1, 44100, 32, Encoding::FLOAT, SFOutputStream::OutFormat::WAV), "invalid float file setup");
    check(!bad.write_frames({std::numeric_limits<float>::quiet_NaN()}) && !bad.close(), "invalid float file write");
  }
  Context context;
  Result invalid_result;
  check(audiowmark_detect_file(context.p, invalid_path.c_str(), &invalid_result.p, nullptr) == AUDIOWMARK_ERROR_ARGUMENT && !invalid_result.p, "nonfinite file input rejected");
  check(audiowmark_add_file(context.p, invalid_path.c_str(), (prefix + "/invalid-out.wav").c_str(), payload_a, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "nonfinite file add rejected");
  check(audiowmark_add_file(context.p, input.c_str(), output.c_str(), payload_a, nullptr) == 0, "Unicode file add");
  check(audiowmark_add_file(context.p, input.c_str(), input.c_str(), payload_a, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "same file rejection");
#ifndef _WIN32
  const std::string alias = prefix + "/alias.wav";
  check(link(input.c_str(), alias.c_str()) == 0, "hardlink setup");
  check(audiowmark_add_file(context.p, input.c_str(), alias.c_str(), payload_a, nullptr) == AUDIOWMARK_ERROR_ARGUMENT, "aliased file rejection");
  unlink(alias.c_str());
#endif
  Result result;
  check(audiowmark_detect_file(context.p, output.c_str(), &result.p, nullptr) == 0 && contains(result, payload_a), "file roundtrip");
  WavData loaded; check(!loaded.load(output) && loaded.n_frames() == wav.n_frames() && loaded.n_channels() == 2 && loaded.sample_rate() == 44100, "file format preserved");
  // Copy to ASCII paths so cmd.exe and shell quoting are immaterial to Unicode ABI coverage.
  const std::string cli_input = prefix + "/in.wav", cli_output = prefix + "/out.wav";
#ifdef _WIN32
  const std::string cli_command = ".\\audiowmark.exe";
#else
  const std::string cli_command = "./audiowmark";
#endif
  check(!wav.save(cli_input) && !loaded.save(cli_output), "CLI setup");
  check(std::system((cli_command + " -q cmp " + cli_output + " 0123456789abcdeffedcba9876543210 > " + prefix + "/cli.log").c_str()) == 0, "library add -> CLI detect");
  check(std::system((cli_command + " -q add " + cli_input + " " + cli_output + " deadbeefc0ffee12abcd9876543210ff").c_str()) == 0, "CLI add");
  Result cli_result;
  check(audiowmark_detect_file(context.p, cli_output.c_str(), &cli_result.p, nullptr) == 0 && contains(cli_result, payload_b), "CLI add -> library detect");
  KeyHandle key("key 0123456789abcdef0123456789abcdef\nname \"key-Łódź\"\n");
  const std::string key_path = prefix + u8"/klucz-Łódź.key";
  check(audiowmark_key_save(key.p, key_path.c_str(), nullptr) == 0, "Unicode key save");
  audiowmark_key *key_copy = nullptr;
  check(audiowmark_key_load(key_path.c_str(), &key_copy, nullptr) == 0 && !std::strcmp(audiowmark_key_export(key.p), audiowmark_key_export(key_copy)), "Unicode key roundtrip");
  const audiowmark_key *keys[] = {key_copy};
  check(audiowmark_context_set_keys(context.p, keys, 1, nullptr) == 0, "copy key ownership");
  audiowmark_key_free(key_copy);
  check(audiowmark_add_file(context.p, cli_input.c_str(), cli_output.c_str(), payload_a, nullptr) == 0, "keyed file add after key free");
  const std::string cli_key = prefix + "/cli.key";
  check(audiowmark_key_save(key.p, cli_key.c_str(), nullptr) == 0, "ASCII CLI key setup");
  check(std::system((cli_command + " -q cmp --key " + cli_key + " " + cli_output + " 0123456789abcdeffedcba9876543210 > " + prefix + "/cli.log").c_str()) == 0, "CLI key interoperability");
  // Results must remain alive after explicit context destruction.
  audiowmark_context_free(context.p); context.p = nullptr;
  check(contains(result, payload_a), "result independent ownership");
}
int main(int argc, char **argv) {
  try {
    check(audiowmark_abi_version() == 1 && *audiowmark_version(), "version accessors");
    keys();
    if (argc == 2 && !std::strcmp(argv[1], "--keys-only")) {
      std::cout << "Native key tests passed\n";
      return 0;
    }
    check(argc == 1, "unknown test argument");
    errors(); pcm_formats(); concurrency(); files_cli();
    std::cout << "Native ABI tests passed\n";
    return 0;
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
