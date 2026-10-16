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

#include "utils.hh"
#include <chrono>
#ifdef _WIN32
#include <windows.h>
// wingdi.h defines ERROR, which collides with the engine's Log::ERROR.
#undef ERROR
#else
#include <sys/resource.h>
#endif
#include "stdarg.h"

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

using std::vector;
using std::string;

double
get_time()
{
  /* return timestamp in seconds as double */
  return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}

void
print_memory_usage (const std::string& where)
{
#ifndef _WIN32
  printf ("=== memory usage (%s): ===\n", where.c_str());

  // Get Peak RSS from getrusage
  struct rusage usage;
  if (getrusage (RUSAGE_SELF, &usage) == 0)
    {
      printf (" - Peak RSS: %.2f MB\n", usage.ru_maxrss / 1024.0);
    }
  else
    {
      perror ("getrusage failed");
    }

  // Get Virtual Memory and Current RSS from /proc/self/statm
  FILE *fp = fopen ("/proc/self/statm", "r");
  if (!fp)
    {
      perror ("Failed to open /proc/self/statm");
      return;
    }

  long page_size = sysconf (_SC_PAGESIZE); // Get page size in bytes
  long vm_size, rss;
  if (fscanf (fp, "%ld %ld", &vm_size, &rss) != 2)
    {
      perror("Failed to read memory usage");
      fclose (fp);
      return;
    }
  fclose (fp);

  printf (" - Current RSS: %.2f MB\n", (rss * page_size) / (1024.0 * 1024.0));
  printf (" - Virtual Memory: %.2f MB\n", (vm_size * page_size) / (1024.0 * 1024.0));
#endif
}

static unsigned char
from_hex_nibble (char c)
{
  int uc = (unsigned char)c;

  if (uc >= '0' && uc <= '9') return uc - (unsigned char)'0';
  if (uc >= 'a' && uc <= 'f') return uc + 10 - (unsigned char)'a';
  if (uc >= 'A' && uc <= 'F') return uc + 10 - (unsigned char)'A';

  return 16;	// error
}

vector<int>
bit_str_to_vec (const string& bits)
{
  vector<int> bitvec;
  for (auto nibble : bits)
    {
      unsigned char c = from_hex_nibble (nibble);
      if (c >= 16)
        return vector<int>(); // error

      bitvec.push_back ((c & 8) > 0);
      bitvec.push_back ((c & 4) > 0);
      bitvec.push_back ((c & 2) > 0);
      bitvec.push_back ((c & 1) > 0);
    }
  return bitvec;
}

string
bit_vec_to_str (const vector<int>& bit_vec)
{
  string bit_str;

  for (size_t pos = 0; pos + 3 < bit_vec.size(); pos += 4) // convert only groups of 4 bits
    {
      int nibble = 0;
      for (int j = 0; j < 4; j++)
        {
          if (bit_vec[pos + j])
            {
              // j == 0 has the highest value, then 1, 2, 3 (lowest)
              nibble |= 1 << (3 - j);
            }
        }
      const char *to_hex = "0123456789abcdef";
      bit_str += to_hex[nibble];
    }
  return bit_str;
}

vector<unsigned char>
hex_str_to_vec (const string& str)
{
  vector<unsigned char> result;

  if ((str.size() % 2) != 0) // even length
    return vector<unsigned char>();

  for (size_t i = 0; i < str.size() / 2; i++)
    {
      unsigned char h = from_hex_nibble (str[i * 2]);
      unsigned char l = from_hex_nibble (str[i * 2 + 1]);
      if (h >= 16 || l >= 16)
        return vector<unsigned char>();

      result.push_back ((h << 4) + l);
    }

  return result;
}

string
vec_to_hex_str (const vector<unsigned char>& vec)
{
  string s;
  for (auto byte : vec)
    s += string_printf ("%02x", byte);

  return s;
}

static string
string_vprintf (const char *format, va_list vargs)
{
  va_list copy;
  va_copy(copy, vargs);
  int length = vsnprintf(nullptr, 0, format, copy);
  va_end(copy);
  if (length < 0) return format;
  vector<char> buffer(size_t(length) + 1);
  vsnprintf(buffer.data(), buffer.size(), format, vargs);
  string s(buffer.data(), size_t(length));

  return s;
}

string
string_printf (const char *format, ...)
{
  va_list ap;

  va_start (ap, format);
  string s = string_vprintf (format, ap);
  va_end (ap);

  return s;
}

static Log log_level = Log::INFO;

void
set_log_level (Log level)
{
  log_level = level;
}

static void
logv (Log log, const char *format, va_list vargs)
{
  if (log >= log_level)
    {
      string s = string_vprintf (format, vargs);

      /* could support custom log function here */
      fprintf (stderr, "%s", s.c_str());
      fflush (stderr);
    }
}

void
error (const char *format, ...)
{
  va_list ap;

  va_start (ap, format);
  logv (Log::ERROR, format, ap);
  va_end (ap);
}

void
warning (const char *format, ...)
{
  va_list ap;

  va_start (ap, format);
  logv (Log::WARNING, format, ap);
  va_end (ap);
}

void
info (const char *format, ...)
{
  va_list ap;

  va_start (ap, format);
  logv (Log::INFO, format, ap);
  va_end (ap);
}

void
debug (const char *format, ...)
{
  va_list ap;

  va_start (ap, format);
  logv (Log::DEBUG, format, ap);
  va_end (ap);
}

#ifdef _WIN32
std::wstring utf8_wide(const std::string& text)
{
  if (text.size() > INT_MAX) throw std::invalid_argument("UTF-8 path too long");
  int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.c_str(), -1, nullptr, 0);
  if (!count) throw std::invalid_argument("Invalid UTF-8");
  std::wstring result(count, 0);
  MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text.c_str(), -1, &result[0], count);
  result.pop_back();
  return result;
}
#endif
FILE *utf8_fopen(const std::string& path, const char *mode)
{
#ifdef _WIN32
  return _wfopen(utf8_wide(path).c_str(), utf8_wide(mode).c_str());
#else
  return fopen(path.c_str(), mode);
#endif
}
