/*
 * Copyright (C) 2020-2026 Stefan Westerfeld and audiowmark contributors
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

/*
 * videowmark: watermark the audio track of a video file.
 *
 * This is the native replacement of the former bash script of the same name. It runs ffprobe,
 * ffmpeg and audiowmark directly (no shell), so it behaves identically on Linux, macOS and Windows.
 * Command line, messages and exit codes follow the script; see manpages/videowmark.1.md.
 */

#include "config.h"
#include "process.hh"
#include "utils.hh"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#endif

using std::string;
using std::vector;

namespace {

const char *const HELP_TEXT =
  "usage: videowmark <command> [ <args>... ]\n"
  "\n"
  "Commands:\n"
  "  * create a watermarked video file with a message\n"
  "    videowmark add <input_video> <watermarked_video> <message_hex>\n"
  "\n"
  "  * retrieve message\n"
  "    videowmark get <watermarked_video>\n"
  "\n"
  "Global options:\n"
  "  --strength <s>        set watermark strength\n"
  "  --key <file>          load watermarking key from file\n"
  "  -q, --quiet           disable information messages\n"
  "  -v, --verbose         enable ffmpeg verbose output\n";

struct Options
{
  vector<string> audiowmark_args;  // forwarded to audiowmark in command line order (-q, --key, --strength)
  vector<string> positional;
  bool           quiet = false;
  bool           verbose = false;
  bool           help = false;
};

int
fail (const string& message)
{
  fprintf (stderr, "videowmark: error: %s\n", message.c_str());
  return 1;
}

bool
starts_with (const string& s, const string& prefix)
{
  return s.compare (0, prefix.size(), prefix) == 0;
}

/* ---------------------------------------------------------------------------------------
 * command line parsing: the subset of GNU getopt_long that the old script relied on
 *  - options may appear before and after the command, "--" ends option parsing
 *  - short options can be bundled (-qv), long options can be abbreviated and use --opt=value
 */

struct LongOption
{
  const char *name;
  bool        has_arg;
  char        id;        // 'v', 'q', 'h', 'k' (--key), 's' (--strength)
};

const LongOption LONG_OPTIONS[] = {
  { "verbose",  false, 'v' },
  { "quiet",    false, 'q' },
  { "help",     false, 'h' },
  { "key",      true,  'k' },
  { "strength", true,  's' },
};

bool
apply_option (Options& options, char id, const string& value)
{
  switch (id)
    {
      case 'v': options.verbose = true; break;
      case 'q': options.quiet = true; options.audiowmark_args.push_back ("-q"); break;
      case 'h': options.help = true; break;
      case 'k': options.audiowmark_args.push_back ("--key"); options.audiowmark_args.push_back (value); break;
      case 's': options.audiowmark_args.push_back ("--strength"); options.audiowmark_args.push_back (value); break;
      default: return false;
    }
  return true;
}

bool
parse_options (const vector<string>& args, Options& options)
{
  bool ok = true;
  for (size_t i = 0; i < args.size(); i++)
    {
      const string& arg = args[i];
      if (arg == "--")
        {
          for (size_t j = i + 1; j < args.size(); j++)
            options.positional.push_back (args[j]);
          break;
        }
      if (starts_with (arg, "--"))
        {
          string name = arg.substr (2);
          string value;
          bool have_value = false;
          size_t equals = name.find ('=');
          if (equals != string::npos)
            {
              value = name.substr (equals + 1);
              name = name.substr (0, equals);
              have_value = true;
            }
          const LongOption *match = nullptr;
          int matches = 0;
          for (const LongOption& candidate : LONG_OPTIONS)
            {
              if (name == candidate.name)
                {
                  match = &candidate;
                  matches = 1;
                  break;
                }
              if (!name.empty() && starts_with (candidate.name, name))
                {
                  match = &candidate;
                  matches++;
                }
            }
          if (matches != 1)
            {
              fprintf (stderr, "videowmark: %s option '--%s'\n", matches ? "ambiguous" : "unrecognized", name.c_str());
              ok = false;
              continue;
            }
          if (match->has_arg)
            {
              if (!have_value)
                {
                  if (i + 1 >= args.size())
                    {
                      fprintf (stderr, "videowmark: option '--%s' requires an argument\n", match->name);
                      ok = false;
                      continue;
                    }
                  value = args[++i];
                }
            }
          else if (have_value)
            {
              fprintf (stderr, "videowmark: option '--%s' doesn't allow an argument\n", match->name);
              ok = false;
              continue;
            }
          apply_option (options, match->id, value);
        }
      else if (arg.size() > 1 && arg[0] == '-')
        {
          for (size_t c = 1; c < arg.size(); c++)
            {
              if (!apply_option (options, arg[c], string()) || arg[c] == 'k' || arg[c] == 's')
                {
                  fprintf (stderr, "videowmark: invalid option -- '%c'\n", arg[c]);
                  ok = false;
                }
            }
        }
      else
        options.positional.push_back (arg);
    }
  return ok;
}

/* ---------------------------------------------------------------------------------------
 * file name helpers
 */

bool
is_separator (char c)
{
#ifdef _WIN32
  return c == '/' || c == '\\';
#else
  return c == '/';
#endif
}

string
base_name (const string& path)
{
  size_t pos = path.size();
  while (pos > 0 && !is_separator (path[pos - 1]))
    pos--;
  return path.substr (pos);
}

string
directory_name (const string& path)
{
  size_t pos = path.size();
  while (pos > 0 && !is_separator (path[pos - 1]))
    pos--;
  if (pos == 0)
    return ".";
  while (pos > 1 && is_separator (path[pos - 1]))
    pos--;
  return path.substr (0, pos);
}

/* extension including the leading dot, empty if there is none */
string
extension (const string& path)
{
  string name = base_name (path);
  size_t dot = name.rfind ('.');
  return dot == string::npos ? string() : name.substr (dot);
}

bool
all_of_class (const string& s, bool (*pred) (char))
{
  if (s.empty())
    return false;
  for (char c : s)
    if (!pred (c))
      return false;
  return true;
}

bool is_hex_digit (char c) { return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); }
bool is_digit (char c) { return c >= '0' && c <= '9'; }
bool is_codec_char (char c) { return (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'; }

/* ---------------------------------------------------------------------------------------
 * ffprobe / ffmpeg
 */

struct StreamInfo
{
  int    audio_streams = 0;
  int    video_streams = 0;
  string codec_name;           // first audio stream
  string bit_rate = "N/A";     // first audio stream
  double audio_start = 0;      // start_time of the first audio / video stream in seconds
  double video_start = 0;
  bool   have_audio_start = false;
  bool   have_video_start = false;
};

/* start_time is "N/A" (or missing) for some containers; only finite values are used */
bool
parse_seconds (const string& text, double& seconds)
{
  if (text.empty() || text == "N/A")
    return false;
  char *end = nullptr;
  double value = strtod (text.c_str(), &end);
  if (end == text.c_str() || *end != 0 || !(value > -1e6 && value < 1e6))
    return false;
  seconds = value;
  return true;
}

class Tools
{
public:
  string ffmpeg, ffprobe, audiowmark;

  Error
  resolve (bool need_audiowmark, bool need_ffmpeg)
  {
    Error err;
    if (need_ffmpeg)
      {
        err = Process::tool ("ffmpeg", ffmpeg);
        if (err)
          return err;
      }
    err = Process::tool ("ffprobe", ffprobe);
    if (err)
      return err;
    if (need_audiowmark)
      {
        err = Process::tool ("audiowmark", audiowmark);
        if (err)
          return err;
      }
    return Error::Code::NONE;
  }
};

Error
probe_streams (const Tools& tools, const string& file, StreamInfo& info)
{
  /* Only fixed fields are requested; stream tags (arbitrary file content) are never part of the output */
  vector<string> lines;
  Error err = Process::run ({ tools.ffprobe, "-v", "error", "-protocol_whitelist", "file", "-show_entries",
                              "stream=codec_type,codec_name,bit_rate,start_time", "-of", "compact", Process::absolute_path (file) },
                            &lines);
  if (err)
    return err;

  for (const string& line : lines)
    {
      if (!starts_with (line, "stream|"))
        continue;

      string codec_type, codec_name, bit_rate = "N/A", start_time;
      size_t pos = 0;
      while (pos <= line.size())
        {
          size_t end = line.find ('|', pos);
          if (end == string::npos)
            end = line.size();
          string field = line.substr (pos, end - pos);
          size_t equals = field.find ('=');
          if (equals != string::npos)
            {
              string key = field.substr (0, equals);
              string value = field.substr (equals + 1);
              if (key == "codec_type")
                codec_type = value;
              else if (key == "codec_name")
                codec_name = value;
              else if (key == "bit_rate")
                bit_rate = value;
              else if (key == "start_time")
                start_time = value;
            }
          pos = end + 1;
        }
      if (codec_type == "audio")
        {
          if (!info.audio_streams)
            {
              info.codec_name = codec_name;
              info.bit_rate = bit_rate;
              info.have_audio_start = parse_seconds (start_time, info.audio_start);
            }
          info.audio_streams++;
        }
      else if (codec_type == "video")
        {
          if (!info.video_streams)
            info.have_video_start = parse_seconds (start_time, info.video_start);
          info.video_streams++;
        }
    }
  return Error::Code::NONE;
}

/* A bit rate is only passed on if it is a positive number an encoder can use; otherwise the encoder
 * default applies (ffprobe reports 0 or N/A for some containers).
 */
bool
usable_bit_rate (const string& codec, const string& bit_rate)
{
  if (bit_rate.empty() || bit_rate.size() > 9 || !all_of_class (bit_rate, is_digit))
    return false;
  long value = atol (bit_rate.c_str());
  if (value <= 0)
    return false;
  if (codec == "mp3")
    return value >= 8000 && value <= 320000;
  return value >= 1000 && value <= 10000000;
}

/* the encoder options the old script derived from ffprobe (used for messages and `probe`) */
string
audio_encode_options (const StreamInfo& info)
{
  if (!info.audio_streams || info.codec_name.empty())
    return string();

  // opus encoder is experimental, ffmpeg recommends libopus for encoding
  string codec = info.codec_name == "opus" ? "libopus" : info.codec_name;
  string result = " -c:a " + codec;
  if (usable_bit_rate (info.codec_name, info.bit_rate))
    result += " -ab " + info.bit_rate;
  return result;
}

struct Encoder
{
  string name;                // ffmpeg encoder
  string codec;               // ffprobe codec_name
  bool   lossy = false;       // whether the bit rate is passed on
};

/* audio codecs supported by add: AAC, MP3, Opus, Vorbis, FLAC and PCM */
bool
select_encoder (const string& codec, Encoder& encoder)
{
  encoder.codec = codec;
  encoder.lossy = true;
  if (codec == "aac")
    encoder.name = "aac";
  else if (codec == "mp3")
    encoder.name = "libmp3lame";
  else if (codec == "opus")
    encoder.name = "libopus";
  else if (codec == "vorbis")
    encoder.name = "libvorbis";
  else if (codec == "flac")
    {
      encoder.name = "flac";
      encoder.lossy = false;
    }
  else if (starts_with (codec, "pcm_") && all_of_class (codec, is_codec_char))
    {
      encoder.name = codec;
      encoder.lossy = false;
    }
  else
    return false;
  return true;
}

Error
check_encoder_available (const Tools& tools, const Encoder& encoder)
{
  vector<string> lines;
  Error err = Process::run ({ tools.ffmpeg, "-hide_banner", "-v", "error", "-nostdin", "-encoders" }, &lines);
  if (err)
    return err;

  for (const string& line : lines)
    {
      /* " A....D aac                  AAC (Advanced Audio Coding)" */
      size_t start = line.find_first_not_of (' ');
      if (start == string::npos)
        continue;
      size_t flags_end = line.find (' ', start);
      if (flags_end == string::npos || flags_end - start != 6 || line[start] != 'A')
        continue;
      size_t name_start = line.find_first_not_of (' ', flags_end);
      if (name_start == string::npos)
        continue;
      size_t name_end = line.find (' ', name_start);
      if (line.substr (name_start, name_end == string::npos ? string::npos : name_end - name_start) == encoder.name)
        return Error::Code::NONE;
    }
  return Error (string_printf ("audio encoder '%s' (for codec '%s') is not available in ffmpeg",
                               encoder.name.c_str(), encoder.codec.c_str()));
}

vector<string>
encoder_args (const Encoder& encoder, const StreamInfo& info)
{
  vector<string> args = { "-c:a", encoder.name };
  if (encoder.lossy && usable_bit_rate (info.codec_name, info.bit_rate))
    {
      args.push_back ("-ab");
      args.push_back (info.bit_rate);
    }
  return args;
}

vector<string>
join (std::initializer_list<vector<string>> parts)
{
  vector<string> result;
  for (const auto& part : parts)
    result.insert (result.end(), part.begin(), part.end());
  return result;
}

/* ---------------------------------------------------------------------------------------
 * commands
 */

class VideoWmark
{
  Options                    m_options;
  Tools                      m_tools;
  const Process::InterruptGuard& m_guard;

  /* Ctrl-C / SIGTERM only set a flag; every stage ends here so temporary files are removed by the
   * normal unwinding and nothing is published after an interruption.
   */
  int
  check_interrupt()
  {
    Error err = m_guard.error();
    return err ? fail (err.message()) : 0;
  }

  vector<string>
  ffmpeg_verbosity() const
  {
    return { "-v", m_options.verbose ? "info" : "error" };
  }

  int
  check_stream_count (const string& file, StreamInfo& info)
  {
    Error err = probe_streams (m_tools, file, info);
    if (err)
      return fail (string_printf ("reading input file streams failed (ffprobe): %s", err.message()));

    if (info.audio_streams != 1 || info.video_streams != 1)
      {
        fprintf (stderr, "videowmark: detected input file stream count: audio=%d:video=%d\n",
                 info.audio_streams, info.video_streams);
        return fail ("input file must have one audio stream and one video stream");
      }
    return 0;
  }

  int
  extract_audio (const string& in_file, const string& wav)
  {
    Error err = Process::run (join ({ { m_tools.ffmpeg }, ffmpeg_verbosity(),
                                      { "-nostdin", "-y", "-protocol_whitelist", "file", "-i", Process::absolute_path (in_file),
                                        "-map", "0:a:0", "-vn", "-f", "wav", "-rf64", "always", wav } }));
    return err ? fail ("extracting audio from video failed (ffmpeg)") : 0;
  }

public:
  VideoWmark (const Options& options, const Process::InterruptGuard& guard) :
    m_options (options),
    m_guard (guard)
  {
  }

  int
  add (const string& in_file, const string& out_file, const string& bits)
  {
    // check file extensions
    string ext_in = extension (in_file);
    string ext_out = extension (out_file);
    if (ext_in != ext_out)
      return fail (string_printf ("input/output extension must match ('%s' vs. '%s')",
                                  ext_in.c_str(), ext_out.c_str()));
    if (!all_of_class (bits, is_hex_digit))
      return fail ("message must be a hexadecimal string");

    Error err = m_tools.resolve (true, true);
    if (err)
      return fail (err.message());

    // check audio/video stream count
    StreamInfo info;
    int rc = check_stream_count (in_file, info);
    if (rc)
      return rc;

    // check that the audio can be encoded again before doing any work (no fallback codec)
    Encoder encoder;
    if (!select_encoder (info.codec_name, encoder))
      return fail (string_printf ("unsupported audio codec '%s' (supported: aac, mp3, opus, vorbis, flac, pcm)",
                                  info.codec_name.c_str()));
    err = check_encoder_available (m_tools, encoder);
    if (err)
      return fail (err.message());

    // never replace the input, and never touch an existing output before the new file is complete
    string out_abs = Process::absolute_path (out_file);
    if (Process::same_file (in_file, out_file))
      return fail ("input and output must be different files");

    Process::TempDir staging;       // next to the output so the final rename is atomic
    err = staging.create (directory_name (out_abs));
    if (err)
      return fail (string_printf ("cannot create temporary files next to the output file: %s", err.message()));
    string staged_video = staging.file ("videowmark-output" + ext_out);

    Process::TempDir work;          // large temporary audio files
    err = work.create();
    if (err)
      return fail (string_printf ("cannot create temporary directory: %s", err.message()));

    vector<string> enc_args = encoder_args (encoder, info);
    err = Process::run (join ({ { m_tools.ffmpeg, "-v", "error", "-nostdin", "-y", "-protocol_whitelist", "file",
                                  "-i", Process::absolute_path (in_file), "-map", "0:a:0", "-vn", "-t", "1" },
                                enc_args, { work.file ("trial" + ext_out) } }));
    if (err)
      return fail (string_printf ("audio codec '%s' cannot be encoded into a '%s' file (ffmpeg)",
                                  info.codec_name.c_str(), ext_out.c_str()));

    rc = check_interrupt();
    if (rc)
      return rc;

    string orig_wav = work.file ("original.wav");
    string wm_wav = work.file ("watermarked.wav");

    // get audio as wav
    rc = extract_audio (in_file, orig_wav);
    if (rc)
      return rc;
    rc = check_interrupt();
    if (rc)
      return rc;

    // watermark
    if (!m_options.quiet)
      fprintf (stderr, "Audio Codec: %s\n", audio_encode_options (info).c_str());
    err = Process::run (join ({ { m_tools.audiowmark, "add" }, m_options.audiowmark_args,
                                { orig_wav, wm_wav, bits, "--set-input-label", in_file, "--set-output-label", out_file,
                                  "--output-format", "rf64" } }));
    if (err)
      return fail ("watermark generation failed (audiowmark)");
    rc = check_interrupt();
    if (rc)
      return rc;

    /* The extracted audio starts at 0. If the original audio started later than the video, that
     * intentional offset has to be restored, otherwise the audio would play too early. (If it started
     * earlier, ffmpeg already aligns the video relative to the earliest stream of the input file.)
     */
    vector<string> offset_args;
    if (info.have_audio_start && info.have_video_start && info.audio_start - info.video_start > 0.0005)
      offset_args = { "-itsoffset", string_printf ("%.6f", info.audio_start - info.video_start) };

    // rejoin
    err = Process::run (join ({ { m_tools.ffmpeg }, ffmpeg_verbosity(),
                                { "-nostdin", "-y", "-protocol_whitelist", "file", "-i", Process::absolute_path (in_file) },
                                offset_args,
                                { "-i", wm_wav, "-c:v", "copy" },
                                enc_args, { "-map", "0:v:0", "-map", "1:a:0", staged_video } }));
    if (err)
      return fail ("merging video and watermarked audio failed (ffmpeg)");
    rc = check_interrupt();
    if (rc)
      return rc;

    err = Process::replace_file (staged_video, out_abs);
    if (err)
      return fail (string_printf ("cannot write output file '%s': %s", out_file.c_str(), err.message()));
    return check_interrupt();
  }

  int
  get (const string& in_file)
  {
    Error err = m_tools.resolve (true, true);
    if (err)
      return fail (err.message());

    StreamInfo info;
    int rc = check_stream_count (in_file, info);
    if (rc)
      return rc;

    Process::TempDir work;
    err = work.create();
    if (err)
      return fail (string_printf ("cannot create temporary directory: %s", err.message()));
    string wav = work.file ("audio.wav");

    rc = extract_audio (in_file, wav);
    if (rc)
      return rc;
    rc = check_interrupt();
    if (rc)
      return rc;

    err = Process::run (join ({ { m_tools.audiowmark, "get" }, m_options.audiowmark_args, { wav } }));
    if (err)
      return fail ("retrieving watermark from audio failed (audiowmark)");
    return check_interrupt();
  }

  int
  probe (const string& in_file)
  {
    Error err = m_tools.resolve (false, false);
    if (err)
      return fail (err.message());

    StreamInfo info;
    err = probe_streams (m_tools, in_file, info);
    if (err)
      return fail (string_printf ("reading input file streams failed (ffprobe): %s", err.message()));
    printf ("%s%s\n", in_file.c_str(), audio_encode_options (info).c_str());
    return 0;
  }
};

int
videowmark_main (const vector<string>& args)
{
  Options options;
  if (!parse_options (args, options))
    return 1;
  if (options.help)
    {
      fputs (HELP_TEXT, stdout);
      return 0;
    }

  Process::InterruptGuard guard;
  Error err = guard.init();
  if (err)
    return fail (string_printf ("cannot install the interrupt handler: %s", err.message()));

  const vector<string>& pos = options.positional;
  VideoWmark videowmark (options, guard);
  if (!pos.empty() && pos[0] == "add" && pos.size() == 4)
    return videowmark.add (pos[1], pos[2], pos[3]);
  if (!pos.empty() && pos[0] == "get" && pos.size() == 2)
    return videowmark.get (pos[1]);
  if (!pos.empty() && pos[0] == "probe" && pos.size() == 2)
    return videowmark.probe (pos[1]);

  fprintf (stderr, "videowmark: error parsing command line arguments (use videowmark -h)\n");
  return 1;
}

} // namespace

int
main (int argc, char **argv)
{
  try
    {
      vector<string> args;
#ifdef _WIN32
      int wide_argc = 0;
      LPWSTR *wide_argv = CommandLineToArgvW (GetCommandLineW(), &wide_argc);
      if (!wide_argv)
        throw std::runtime_error ("Cannot read Unicode command line");
      struct FreeArgv { LPWSTR *p; ~FreeArgv() { LocalFree (p); } } owner { wide_argv };
      for (int i = 1; i < wide_argc; i++)
        {
          int n = WideCharToMultiByte (CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1, nullptr, 0, nullptr, nullptr);
          if (!n)
            throw std::runtime_error ("Invalid Unicode command line");
          string arg (size_t (n), 0);
          WideCharToMultiByte (CP_UTF8, WC_ERR_INVALID_CHARS, wide_argv[i], -1, &arg[0], n, nullptr, nullptr);
          arg.pop_back();
          args.push_back (std::move (arg));
        }
      (void) argc;
      (void) argv;
#else
      for (int i = 1; i < argc; i++)
        args.push_back (argv[i]);
#endif
      return videowmark_main (args);
    }
  catch (const std::exception& e)
    {
      fprintf (stderr, "videowmark: %s\n", e.what());
      return 1;
    }
}
