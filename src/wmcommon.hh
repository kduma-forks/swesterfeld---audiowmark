/*
 * Copyright (C) 2018-2020 Stefan Westerfeld
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

#ifndef AUDIOWMARK_WM_COMMON_HH
#define AUDIOWMARK_WM_COMMON_HH

#include <array>
#include <complex>

#include "random.hh"
#include "rawinputstream.hh"
#include "wavdata.hh"
#include "fft.hh"

#include <assert.h>

enum class Format { AUTO = 1, RAW, RF64, WAV_PIPE };

class Params
{
public:
  static constexpr size_t frame_size      = 1024;

  static constexpr size_t bands_per_frame = 30;
  static constexpr int max_band          = 100;
  static constexpr int min_band          = 20;

  static constexpr int sync_bits           = 6;
  static constexpr int sync_frames_per_bit = 85;
  static constexpr int sync_search_step    = 256;
  static constexpr int sync_search_fine    = 8;

  static constexpr size_t frames_pad_start = 250; // padding at start, in case track starts with silence
  static constexpr int mark_sample_rate = 44100; // watermark generation and detection sample rate

  static constexpr double limiter_block_size_ms = 1000;
  static constexpr double limiter_ceiling       = 0.99;


};

class EngineConfig
{
public:
  int frames_per_bit = 2;
  double water_delta = 0.01;
  std::string json_output;
  bool strict = false;
  bool mix = true;
  bool hard = false;
  bool snr = false;
  bool detect_speed = false;
  bool detect_speed_patient = false;
  double try_speed = -1;
  double test_speed = -1;
  size_t payload_size = 128;
  bool payload_short = false;
  double sync_threshold2 = 0.35;
  int get_n_best = 8;
  double get_chunk_size = 30;
  int test_cut = 0;
  bool test_no_sync = false;
  bool test_no_limiter = false;
  int test_truncate = 0;
  int expect_matches = -1;
  Format input_format = Format::AUTO;
  Format output_format = Format::AUTO;
  RawFormat raw_input_format;
  RawFormat raw_output_format;
  int hls_bit_rate = 0;
  std::string input_label;
  std::string output_label;
  size_t short_k = 0; // immutable short-code selection inherited by CLI workers
  unsigned workers = 0; // CLI: hardware concurrency; SDK: explicit limit
  bool quiet = false;
};

EngineConfig& params();
class ConfigScope
{
  EngineConfig *previous;
public:
  explicit ConfigScope (EngineConfig& config);
  ~ConfigScope();
  ConfigScope(const ConfigScope&) = delete;
};

typedef std::array<int, 30> UpDownArray;
class UpDownGen
{
  Random::Stream    random_stream;
  Random            random;
  std::vector<int>  bands_reorder;

public:
  UpDownGen (const Key& key, Random::Stream random_stream) :
    random_stream (random_stream),
    random (key, 0, random_stream),
    bands_reorder (Params::max_band - Params::min_band + 1)
  {
    UpDownArray x;
    assert (x.size() == Params::bands_per_frame);
  }
  void
  get (int f, UpDownArray& up, UpDownArray& down)
  {
    for (size_t i = 0; i < bands_reorder.size(); i++)
      bands_reorder[i] = Params::min_band + i;

    random.seed (f, random_stream); // use per frame random seed
    random.shuffle (bands_reorder);

    assert (2 * Params::bands_per_frame < bands_reorder.size());
    for (size_t i = 0; i < Params::bands_per_frame; i++)
      {
        up[i]   = bands_reorder[i];
        down[i] = bands_reorder[Params::bands_per_frame + i];
      }
  }
};

class BitPosGen
{
  std::vector<int> pos_vec;

public:
  BitPosGen (const Key& key);
  int sync_frame (int f);
  int data_frame (int f);
};

class FFTAnalyzer
{
  int           m_n_channels = 0;
  std::vector<float> m_window;
  FFTProcessor  m_fft_processor;
public:
  FFTAnalyzer (int n_channels);

  std::vector<std::vector<std::complex<float>>> run_fft (const std::vector<float>& samples, size_t start_index);
  std::vector<std::vector<std::complex<float>>> fft_range (const std::vector<float>& samples, size_t start_index, size_t frame_count);

  static std::vector<float> gen_normalized_window (size_t n_values);
};

struct MixEntry
{
  int  frame;
  int  up;
  int  down;
};

std::vector<MixEntry> gen_mix_entries (const Key& key);

size_t mark_data_frame_count();
size_t mark_sync_frame_count();

int frame_count (const WavData& wav_data);

std::vector<int> parse_payload (const std::string& str);

template<class T> std::vector<T>
randomize_bit_order (const Key& key, const std::vector<T>& bit_vec, bool encode)
{
  std::vector<unsigned int> order;

  for (size_t i = 0; i < bit_vec.size(); i++)
    order.push_back (i);

  Random random (key, /* seed */ 0, Random::Stream::bit_order);
  random.shuffle (order);

  std::vector<T> out_bits (bit_vec.size());
  for (size_t i = 0; i < bit_vec.size(); i++)
    {
      if (encode)
        out_bits[i] = bit_vec[order[i]];
      else
        out_bits[order[i]] = bit_vec[i];
    }
  return out_bits;
}

inline double
window_cos (double x) /* von Hann window */
{
  if (fabs (x) > 1)
    return 0;
  return 0.5 * cos (x * M_PI) + 0.5;
}

inline double
window_hamming (double x) /* sharp (rectangle) cutoffs at boundaries */
{
  if (fabs (x) > 1)
    return 0;

  return 0.54 + 0.46 * cos (M_PI * x);
}

static inline float
db_from_complex (float re, float im, float min_dB)
{
  float abs2 = re * re + im * im;

  if (abs2 > 0)
    {
      constexpr float log2_db_factor = 3.01029995663981; // 10 / log2 (10)

      // glibc log2f is a lot faster than glibc log10
      return log2f (abs2) * log2_db_factor;
    }
  else
    return min_dB;
}

static inline float
db_from_complex (std::complex<float> f, float min_dB)
{
  return db_from_complex (f.real(), f.imag(), min_dB);
}

int add_stream_watermark (const Key& key, AudioInputStream *in_stream, AudioOutputStream *out_stream, const std::string& bits, size_t zero_frames);
int add_watermark (const Key& key, const std::string& infile, const std::string& outfile, const std::string& bits);
struct EngineDetection {
  std::vector<int> bits;
  uint32_t key_index, block_type;
  std::string key_name;
  double time, quality, decode_error, ranking, speed;
};
int get_watermark (const std::vector<Key>& key_list, const std::string& infile, const std::string& orig_pattern);
std::vector<EngineDetection> detect_watermark(const std::vector<Key>& keys, std::unique_ptr<AudioInputStream> stream);

#endif /* AUDIOWMARK_WM_COMMON_HH */
