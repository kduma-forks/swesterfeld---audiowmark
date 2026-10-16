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

#include <string>
#include <regex>

#include "utils.hh"
#include "process.hh"
#include "mpegts.hh"
#include "sfinputstream.hh"
#include "sfoutputstream.hh"
#include "wmcommon.hh"
#include "wavdata.hh"

#include "config.h"

using std::string;
using std::vector;
using std::regex;
using std::map;
using std::min;

#if !HAVE_FFMPEG
int
hls_prepare (const string& in_dir, const string& out_dir, const string& filename, const string& audio_master)
{
  error ("audiowmark: hls support is not available in this build of audiowmark\n");
  return 1;
}

int
hls_add (const Key& key, const string& infile, const string& outfile, const string& bits)
{
  error ("audiowmark: hls support is not available in this build of audiowmark\n");
  return 1;
}
#else

#include "hlsoutputstream.hh"

static bool
file_exists (const string& filename)
{
  return Process::is_regular_file (filename);
}

static string
args2string (const vector<string>& args)
{
  string result;
  bool first = true;

  for (auto a : args)
    {
      if (!first)
        result += " ";
      first = false;
      result += a;
    }
  return result;
}

/* Run a helper program (ffmpeg / ffprobe) without a shell: it is resolved beside the audiowmark
 * executable first (always, if the build requires bundled tools), file arguments must be absolute
 * (see Process::absolute_path), so they can neither be mistaken for options nor for URLs.
 */
static Error
run (const vector<string>& args, vector<string> *pipe_out = nullptr)
{
  auto report_error = [=] { error ("audiowmark: failed to execute %s\n", args2string (args).c_str()); };

  vector<string> argv = args;
  Error err = Process::tool (args[0], argv[0]);
  if (err)
    {
      report_error();
      return err;
    }
  err = Process::run (argv, pipe_out);
  if (err)
    report_error();
  return err;
}

/* HLS segment names are read from a playlist, so they must stay below the input and output directories */
static bool
segment_name_ok (const string& name)
{
  if (name.empty() || name[0] == '/' || name[0] == '\\' || name.find (':') != string::npos)
    return false;

  string component;
  for (char c : name + "/")
    {
      if (c == '/' || c == '\\')
        {
          if (component == "..")
            return false;
          component.clear();
        }
      else
        component += c;
    }
  return true;
}

Error
ff_decode (const string& filename, WavData& out_wav_data)
{
  Process::TempDir temp_dir;
  Error err = temp_dir.create();
  if (err)
    return err;
  string tmp_file_name = temp_dir.file ("decoded.wav");

  err = run ({"ffmpeg", "-v", "error", "-nostdin", "-y", "-f",  "mpegts", "-i", Process::absolute_path (filename), "-f", "wav", tmp_file_name});
  if (err)
    return err;

  err = out_wav_data.load (tmp_file_name);
  return err;
}

static int
hls_add_to_file (const Key& key, const string& infile, const string& outfile, const string& bits)
{
  TSReader reader;

  Error err = reader.load (infile);
  if (err)
    {
      error ("hls: %s\n", err.message());
      return 1;
    }

  const TSReader::Entry *full_flac = reader.find ("full.flac");
  if (!full_flac)
    {
      error ("hls: no embedded context found in %s\n", infile.c_str());
      return 1;
    }

  SFInputStream in_stream;
  err = in_stream.open (&full_flac->data);
  if (err)
    {
      error ("hls: %s\n", err.message());
      return 1;
    }

  map<string, string> vars = reader.parse_vars ("vars");
  bool missing_vars = false;

  auto get_var = [&] (const std::string& var) {
    auto it = vars.find (var);
    if (it == vars.end())
      {
        error ("audiowmark: hls segment is missing value for required variable '%s'\n", var.c_str());
        missing_vars = true;
        return "";
      }
    else
      return it->second.c_str();
  };
  size_t start_pos = atoi (get_var ("start_pos"));
  size_t prev_size = atoi (get_var ("prev_size"));
  size_t size      = atoi (get_var ("size"));
  double pts_start = atof (get_var ("pts_start"));
  int    bit_rate  = atoi (get_var ("bit_rate"));
  size_t prev_ctx  = min<size_t> (1024 * 3, prev_size);

  string channel_layout = get_var ("channel_layout");

  if (missing_vars)
    return 1;

  if (Params::hls_bit_rate)  // command line option overrides vars bit-rate
    bit_rate = Params::hls_bit_rate;

  HLSOutputStream out_stream (in_stream.n_channels(), in_stream.sample_rate(), in_stream.bit_depth());

  out_stream.set_bit_rate (bit_rate);
  out_stream.set_channel_layout (channel_layout);

  /* ffmpeg aac encode adds one frame of latency - it would be possible to compensate for this
   * by setting shift = 1024, but it can also be done by adjusting the presentation timestamp
   */
  const size_t shift = 0;
  const size_t cut_aac_frames = (prev_ctx + shift) / 1024;
  const size_t delete_input_start = prev_size - prev_ctx;
  const size_t keep_aac_frames = size / 1024;

  err = out_stream.open (outfile, cut_aac_frames, keep_aac_frames, pts_start, delete_input_start);
  if (err)
    {
      error ("audiowmark: error opening HLS output stream %s: %s\n", outfile.c_str(), err.message());
      return 1;
    }

  int wm_rc = add_stream_watermark (key, &in_stream, &out_stream, bits, start_pos - prev_size);
  if (wm_rc != 0)
    return wm_rc;

  info ("AAC Bitrate:  %d\n", bit_rate);
  return 0;
}

static string
parent_directory (const string& path)
{
  size_t pos = path.find_last_of (
#ifdef _WIN32
    "/\\"
#else
    "/"
#endif
  );
  if (pos == string::npos)
    return ".";
  return pos == 0 ? path.substr (0, 1) : path.substr (0, pos);
}

/* A named output file is written next to its destination and only moved into place after the segment
 * was complete, so a failed run never truncates or removes an existing output. Stdout ("-") is streamed.
 */
int
hls_add (const Key& key, const string& infile, const string& outfile, const string& bits)
{
  Process::InterruptGuard guard;
  Error init_err = guard.init();
  if (init_err)
    {
      error ("audiowmark: hls: cannot install the interrupt handler: %s\n", init_err.message());
      return 1;
    }

  if (outfile == "-")
    {
      int stream_rc = hls_add_to_file (key, infile, outfile, bits);
      Error interrupted = guard.error();
      if (stream_rc == 0 && interrupted)
        {
          error ("audiowmark: hls: %s\n", interrupted.message());
          return 1;
        }
      return stream_rc;
    }

  if (infile != "-" && Process::same_file (infile, outfile))
    {
      error ("audiowmark: hls: input and output must be different files\n");
      return 1;
    }

  string destination = Process::absolute_path (outfile);
  Process::TempDir staging;
  Error err = staging.create (parent_directory (destination));
  if (err)
    {
      error ("audiowmark: hls: cannot create temporary file next to %s: %s\n", outfile.c_str(), err.message());
      return 1;
    }
  string staged = staging.file ("segment.ts");

  int rc = hls_add_to_file (key, infile, staged, bits);
  if (rc != 0)
    return rc;
  err = guard.error();
  if (err)
    {
      error ("audiowmark: hls: %s\n", err.message());
      return 1;
    }

  err = Process::replace_file (staged, destination);
  if (err)
    {
      error ("audiowmark: hls: cannot write %s: %s\n", outfile.c_str(), err.message());
      return 1;
    }
  return 0;
}

Error
bit_rate_from_m3u8 (const string& m3u8, const WavData& wav_data, int& bit_rate)
{
  Process::TempDir temp_dir;
  Error err = temp_dir.create();
  if (err)
    return err;
  string tmp_file_name = temp_dir.file ("audio.aac");

  err = run ({"ffmpeg", "-v", "error", "-nostdin", "-y", "-i", Process::absolute_path (m3u8), "-c:a", "copy", "-f", "adts", tmp_file_name});
  if (err)
    return err;

  uint64_t size = 0;
  err = Process::file_size (tmp_file_name, size);
  if (err)
    return Error (string_printf ("failed to stat temporary aac file: %s", err.message()));

  double seconds = double (wav_data.n_frames()) / wav_data.sample_rate();
  bit_rate = size / seconds * 8;
  return Error::Code::NONE;
}

Error
load_audio_master (const string& filename, WavData& audio_master_data)
{
  Process::TempDir temp_dir;
  Error err = temp_dir.create();
  if (err)
    return err;
  string tmp_file_name = temp_dir.file ("master.wav");

  /* extract wav */
  err = run ({"ffmpeg", "-v", "error", "-nostdin", "-y", "-i", Process::absolute_path (filename), "-f", "wav", tmp_file_name});
  if (err)
    return err;

  err = audio_master_data.load (tmp_file_name);
  if (err)
    return err;

  return Error::Code::NONE;
}

Error
probe_input_segment (const string& filename, map<string, string>& params)
{
  TSReader reader;

  Error err = reader.load (filename);
  if (err)
    {
      error ("audiowmark: hls: failed to read mpegts input file: %s\n", filename.c_str());
      return err;
    }

  if (reader.entries().size())
    {
      error ("audiowmark: hls: file appears to be already prepared: %s\n", filename.c_str());
      return Error ("input for hls-prepare must not contain context");
    }

  vector<string> format_out;
  err = run ({"ffprobe", "-v", "error", "-print_format", "compact", "-show_entries", "stream=index,codec_name,channels,channel_layout,start_time", Process::absolute_path (filename)}, &format_out);
  if (err)
    {
      error ("audiowmark: hls: failed to validate input file: %s\n", filename.c_str());
      return err;
    }
  for (auto o : format_out)
    {
      /* parse assignments stream|index=0|codec_name=aac|... */
      string key, value;
      bool in_key = true;
      for (char c : '|' + o + '|')
        {
          if (c == '=')
            {
              in_key = false;
            }
          else if (c == '|')
            {
              params[key] = value;
              in_key = true;
              key = "";
              value = "";
            }
          else
            {
              if (in_key)
                key += c;
              else
                value += c;
            }
        }
    }
  return Error::Code::NONE;
}

int
hls_prepare (const string& in_dir, const string& out_dir, const string& filename, const string& audio_master)
{
  Process::InterruptGuard guard;
  Error guard_err = guard.init();
  if (guard_err)
    {
      error ("audiowmark: hls: cannot install the interrupt handler: %s\n", guard_err.message());
      return 1;
    }
  auto interrupted = [&] {
    Error e = guard.error();
    if (e)
      error ("audiowmark: hls: %s\n", e.message());
    return bool (e);
  };

  string in_name = in_dir + "/" + filename;
  FILE *in_file = utf8_fopen (in_name, "rb");
  ScopedFile in_file_s (in_file);

  if (!in_file)
    {
      error ("audiowmark: error opening input playlist %s\n", in_name.c_str());
      return 1;
    }

  /* the playlist is copied byte for byte (line endings included); it is only parsed for segment names */
  string playlist;
  {
    char buffer[4096];
    size_t count;
    while ((count = fread (buffer, 1, sizeof (buffer), in_file)) > 0)
      playlist.append (buffer, count);
    if (ferror (in_file))
      {
        error ("audiowmark: error reading input playlist %s\n", in_name.c_str());
        return 1;
      }
  }

  struct Segment
  {
    string              name;
    size_t              size;
    map<string, string> vars;
  };
  vector<Segment> segments;
  const regex blank_re (R"(\s*(#.*)?)");
  for (size_t pos = 0; pos < playlist.size();)
    {
      size_t eol = playlist.find ('\n', pos);
      if (eol == string::npos)
        eol = playlist.size();
      string line = playlist.substr (pos, eol - pos);
      pos = eol + 1;
      while (!line.empty() && line.back() == '\r')
        line.pop_back();

      if (line.size() > 4096)
        {
          error ("audiowmark: line too long in playlist %s\n", in_name.c_str());
          return 1;
        }
      if (regex_match (line, blank_re))
        continue;   /* blank line or comment */

      if (!segment_name_ok (line))
        {
          error ("audiowmark: unsafe segment name in playlist: %s\n", line.c_str());
          return 1;
        }
      Segment segment;
      segment.name = line;
      segments.push_back (segment);
    }

  Error mkerr = Process::make_directory (out_dir);
  if (mkerr)
    {
      error ("audiowmark: unable to create directory %s: %s\n", out_dir.c_str(), mkerr.message());
      return 1;
    }

  string out_name = out_dir + "/" + filename;
  if (file_exists (out_name))
    {
      error ("audiowmark: output file already exists: %s\n", out_name.c_str());
      return 1;
    }
  FILE *out_file = utf8_fopen (out_name, "wb");
  ScopedFile out_file_s (out_file);

  if (!out_file)
    {
      error ("audiowmark: error opening output playlist %s\n", out_name.c_str());
      return 1;
    }
  if (fwrite (playlist.data(), 1, playlist.size(), out_file) != playlist.size() || fflush (out_file) != 0)
    {
      error ("audiowmark: error writing output playlist %s\n", out_name.c_str());
      return 1;
    }

  WavData audio_master_data;
  Error err = load_audio_master (audio_master, audio_master_data);
  if (err)
    {
      error ("audiowmark: failed to load audio master: %s\n", audio_master.c_str());
      return 1;
    }

  for (auto& segment : segments)
    {
      if (interrupted())
        return 1;
      map<string, string> params;
      string segname = in_dir + "/" + segment.name;

      Error err = probe_input_segment (segname, params);
      if (err)
        {
          error ("audiowmark: hls: %s\n", err.message());
          return 1;
        }
      /* validate input segment */
      if (atoi (params["index"].c_str()) != 0)
        {
          error ("audiowmark: hls segment '%s' contains more than one stream\n", segname.c_str());
          return 1;
        }
      if (params["codec_name"] != "aac")
        {
          error ("audiowmark: hls segment '%s' is not encoded using AAC\n", segname.c_str());
          return 1;
        }
      int segment_channels = atoi (params["channels"].c_str());
      if (segment_channels != audio_master_data.n_channels())
        {
          error ("audiowmark: number of channels mismatch:\n - hls segment '%s' has %d channels\n - audio master '%s' has %d channels\n",
                 segname.c_str(), segment_channels, audio_master.c_str(), audio_master_data.n_channels());
          return 1;
        }

      /* get segment parameters */
      if (params["channel_layout"].empty())
        {
          error ("audiowmark: hls segment '%s' has no channel_layout entry\n", segname.c_str());
          return 1;
        }
      segment.vars["channel_layout"] = params["channel_layout"];

      /* get start pts */
      if (params["start_time"].empty())
        {
          error ("audiowmark: hls segment '%s' has no start_time entry\n", segname.c_str());
          return 1;
        }
      segment.vars["pts_start"] = params["start_time"];
    }

  /* find bitrate for AAC encoder */
  int bit_rate = 0;
  if (!Params::hls_bit_rate)
    {
      err = bit_rate_from_m3u8 (in_dir + "/" + filename, audio_master_data, bit_rate);
      if (err)
        {
          error ("audiowmark: bit-rate detection failed: %s\n", err.message());
          return 1;
         }
      info ("AAC Bitrate:  %d (detected)\n", bit_rate);
    }
  else
    {
      bit_rate = Params::hls_bit_rate;
      info ("AAC Bitrate:  %d\n", bit_rate);
    }

  info ("Segments:     %zd\n", segments.size());
  size_t start_pos = 0;
  for (auto& segment : segments)
    {
      if (interrupted())
        return 1;
      WavData out;
      Error err = ff_decode (in_dir + "/" + segment.name, out);
      if (err)
        {
          error ("audiowmark: hls: ff_decode failed: %s\n", err.message());
          return 1;
        }
      segment.size = out.n_values() / out.n_channels();

      if ((segment.size % 1024) != 0)
        {
          error ("audiowmark: hls input segments need 1024-sample alignment (due to AAC)\n");
          return 1;
        }

      /* store 3 seconds of the context before this segment and after this segment (if available) */
      const size_t ctx_3sec = 3 * out.sample_rate();
      const size_t prev_size = min<size_t> (start_pos, ctx_3sec);
      const size_t segment_size_with_ctx = prev_size + segment.size + ctx_3sec;

      segment.vars["start_pos"] = string_printf ("%zd", start_pos);
      segment.vars["size"] = string_printf ("%zd", segment.size);
      segment.vars["prev_size"] = string_printf ("%zd", prev_size);
      segment.vars["bit_rate"] = string_printf ("%d", bit_rate);

      /* write audio segment with context */
      const size_t start_point = min (start_pos - prev_size, audio_master_data.n_frames());
      const size_t end_point = min (start_point + segment_size_with_ctx, audio_master_data.n_frames());

      vector<float> out_signal (audio_master_data.samples().begin() + start_point * audio_master_data.n_channels(),
                                audio_master_data.samples().begin() + end_point * audio_master_data.n_channels());

      // append zeros if audio master is too short to provide segment with context
      out_signal.resize (segment_size_with_ctx * audio_master_data.n_channels());

      vector<unsigned char> full_flac_mem;
      SFOutputStream out_stream;
      err = out_stream.open (&full_flac_mem,
                             audio_master_data.n_channels(), audio_master_data.sample_rate(), audio_master_data.bit_depth(),
                             Encoding::SIGNED, /* flac does not support floating point audio */
                             SFOutputStream::OutFormat::FLAC);
      if (err)
        {
          error ("audiowmark: hls: open context flac failed: %s\n", err.message());
          return 1;
        }

      err = out_stream.write_frames (out_signal);
      if (err)
        {
          error ("audiowmark: hls: write context flac failed: %s\n", err.message());
          return 1;
        }

      err = out_stream.close();
      if (err)
        {
          error ("audiowmark: hls: close context flac failed: %s\n", err.message());
          return 1;
        }

      /* store everything we need in a mpegts file */
      TSWriter writer;

      writer.append_data ("full.flac", full_flac_mem);
      writer.append_vars ("vars", segment.vars);

      string out_segment = out_dir + "/" + segment.name;
      if (file_exists (out_segment))
        {
          error ("audiowmark: output file already exists: %s\n", out_segment.c_str());
          return 1;
        }
      err = writer.process (in_dir + "/" + segment.name, out_segment);
      if (err)
        {
          error ("audiowmark: processing hls segment %s failed: %s\n", segment.name.c_str(), err.message());
          return 1;
        }

      /* start position for the next segment */
      start_pos += segment.size;
    }
  if (interrupted())
    return 1;
  int orig_seconds = start_pos / audio_master_data.sample_rate();
  info ("Time:         %d:%02d\n", orig_seconds / 60, orig_seconds % 60);
  return 0;
}
#endif
