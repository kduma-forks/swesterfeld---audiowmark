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

#include "random.hh"
#include "utils.hh"

#include <regex>
#include <mutex>
#include <sstream>

#include <assert.h>
#include <cerrno>
#ifdef _WIN32
#include <windows.h>
#include <bcrypt.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

using std::string;
using std::vector;
using std::regex;
using std::regex_match;

static void
gcrypt_init()
{
  static std::once_flag once;
  std::call_once(once, [] {
    if (!gcry_check_version(GCRYPT_VERSION))
      throw std::runtime_error("libgcrypt version mismatch");
    if (!gcry_control(GCRYCTL_INITIALIZATION_FINISHED_P))
      gcry_control(GCRYCTL_INITIALIZATION_FINISHED, 0);
  });
}


static constexpr auto        GCRY_CIPHER = GCRY_CIPHER_AES128;

static void
uint64_to_buffer (uint64_t       u,
                  unsigned char *buffer)
{
  /* this has to be endian independent: use big endian order */
  buffer[0] = u >> 56;
  buffer[1] = u >> 48;
  buffer[2] = u >> 40;
  buffer[3] = u >> 32;
  buffer[4] = u >> 24;
  buffer[5] = u >> 16;
  buffer[6] = u >> 8;
  buffer[7] = u;
}

static uint64_t
uint64_from_buffer (unsigned char *buffer)
{
  /* this has to be endian independent: use big endian order */
  return (uint64_t (buffer[0]) << 56)
       + (uint64_t (buffer[1]) << 48)
       + (uint64_t (buffer[2]) << 40)
       + (uint64_t (buffer[3]) << 32)
       + (uint64_t (buffer[4]) << 24)
       + (uint64_t (buffer[5]) << 16)
       + (uint64_t (buffer[6]) << 8)
       + buffer[7];
}

#if 0 /* debugging only */
static void
print (const string& label, const vector<unsigned char>& data)
{
  printf ("%s: ", label.c_str());
  for (auto ch : data)
    printf ("%02x ", ch);
  printf ("\n");
}
#endif

Random::Random (const Key& key, uint64_t start_seed, Stream stream)
{
  gcrypt_init();

  try {
  gcry_error_t gcry_ret = gcry_cipher_open (&aes_ctr_cipher, GCRY_CIPHER, GCRY_CIPHER_MODE_CTR, 0);
  die_on_error ("gcry_cipher_open", gcry_ret);

  gcry_ret = gcry_cipher_setkey (aes_ctr_cipher, key.aes_key(), Key::SIZE);
  die_on_error ("gcry_cipher_setkey", gcry_ret);

  gcry_ret = gcry_cipher_open (&seed_cipher, GCRY_CIPHER, GCRY_CIPHER_MODE_ECB, 0);
  die_on_error ("gcry_cipher_open", gcry_ret);

  gcry_ret = gcry_cipher_setkey (seed_cipher, key.aes_key(), Key::SIZE);
  die_on_error ("gcry_cipher_setkey", gcry_ret);

  seed (start_seed, stream);
  } catch (...) {
    if (aes_ctr_cipher) gcry_cipher_close(aes_ctr_cipher);
    if (seed_cipher) gcry_cipher_close(seed_cipher);
    throw;
  }
}

void
Random::seed (uint64_t seed, Stream stream)
{
  buffer_pos = 0;
  buffer.clear();

  unsigned char plain_text[Key::SIZE];
  unsigned char cipher_text[Key::SIZE];

  memset (plain_text, 0, sizeof (plain_text));
  uint64_to_buffer (seed, &plain_text[0]);

  plain_text[8] = uint8_t (stream);

  gcry_error_t gcry_ret = gcry_cipher_encrypt (seed_cipher, &cipher_text[0], Key::SIZE,
                                                            &plain_text[0],  Key::SIZE);
  die_on_error ("gcry_cipher_encrypt", gcry_ret);

  gcry_ret = gcry_cipher_setctr (aes_ctr_cipher, &cipher_text[0], Key::SIZE);
  die_on_error ("gcry_cipher_setctr", gcry_ret);
}

Random::~Random()
{
  gcry_cipher_close (aes_ctr_cipher);
  gcry_cipher_close (seed_cipher);
}

void
Random::refill_buffer()
{
  const size_t block_size = 256;
  static const unsigned char zeros[block_size] = { 0, };
  unsigned char cipher_text[block_size];

  gcry_error_t gcry_ret = gcry_cipher_encrypt (aes_ctr_cipher, cipher_text, block_size, zeros, block_size);
  die_on_error ("gcry_cipher_encrypt", gcry_ret);

  // print ("AES OUT", {cipher_text, cipher_text + block_size});

  buffer.clear();
  for (size_t i = 0; i < block_size; i += 8)
    buffer.push_back (uint64_from_buffer (cipher_text + i));

  buffer_pos = 0;
}

void
Random::die_on_error (const char *func, gcry_error_t err)
{
  if (err) throw std::runtime_error(string_printf("%s failed: %s/%s", func, gcry_strsource(err), gcry_strerror(err)));
}

string
Random::gen_key()
{
  vector<unsigned char> key (Key::SIZE);
  // Obtain key material directly from the OS. This avoids allocating gcrypt's
  // process-global entropy cache or changing a host's secure-memory policy.
#ifdef _WIN32
  if (BCryptGenRandom(nullptr, key.data(), static_cast<ULONG>(key.size()),
                      BCRYPT_USE_SYSTEM_PREFERRED_RNG) < 0)
    throw std::runtime_error("System random generator failed");
#else
  int flags = O_RDONLY;
#ifdef O_CLOEXEC
  flags |= O_CLOEXEC;
#endif
  int fd;
  do { fd = open("/dev/urandom", flags); } while (fd < 0 && errno == EINTR);
  if (fd < 0) throw std::runtime_error("Cannot open system random generator");
  struct CloseFd { int fd; ~CloseFd() { close(fd); } } owner{fd};
  size_t offset = 0;
  while (offset < key.size()) {
    const auto n = read(fd, key.data() + offset, key.size() - offset);
    if (n < 0 && errno == EINTR) continue;
    if (n <= 0) throw std::runtime_error("Cannot read system random generator");
    offset += static_cast<size_t>(n);
  }
#endif
  return vec_to_hex_str (key);
}

uint64_t
Random::seed_from_hash (const vector<float>& floats)
{
  gcrypt_init();
  unsigned char hash[20];
  gcry_md_hash_buffer (GCRY_MD_SHA1, hash, floats.data(), floats.size() * sizeof (float));
  return uint64_from_buffer (hash);
}

Key::Key() :
  m_aes_key (SIZE)
{
}

Key::~Key()
{
  std::fill (m_aes_key.begin(), m_aes_key.end(), 0);
}

void
Key::set_test_key (uint64_t key)
{
  uint64_to_buffer (key, m_aes_key.data());
  m_name = string_printf ("test-key-%" PRId64, key);
}

static bool
string_chars (char ch)
{
  if ((ch >= 'A' && ch <= 'Z')
  ||  (ch >= '0' && ch <= '9')
  ||  (ch >= 'a' && ch <= 'z')
  ||  (ch == '.')
  ||  (ch == ':')
  ||  (ch == '=')
  ||  (ch == '/')
  ||  (ch == '-')
  ||  (ch == '_'))
    return true;

  return false;
}

static bool
white_space (char ch)
{
  return (ch == ' ' || ch == '\n' || ch == '\t' || ch == '\r');
}

static bool
tokenize (const string& line, vector<string>& tokens)
{
  enum { BLANK, STRING, QUOTED_STRING, QUOTED_STRING_ESCAPED, COMMENT } state = BLANK;
  string s;

  string xline = line + '\n';
  tokens.clear();
  for (string::const_iterator i = xline.begin(); i != xline.end(); i++)
    {
      if (state == BLANK && string_chars (*i))
        {
          state = STRING;
          s += *i;
        }
      else if (state == BLANK && *i == '"')
        {
          state = QUOTED_STRING;
        }
      else if (state == BLANK && white_space (*i))
        {
          // ignore more whitespaces if we've already seen one
        }
      else if (state == STRING && string_chars (*i))
        {
          s += *i;
        }
      else if ((state == STRING && white_space (*i))
           ||  (state == QUOTED_STRING && *i == '"'))
        {
          tokens.push_back (s);
          s = "";
          state = BLANK;
        }
      else if (state == QUOTED_STRING && *i == '\\')
        {
          state = QUOTED_STRING_ESCAPED;
        }
      else if (state == QUOTED_STRING)
        {
          s += *i;
        }
      else if (state == QUOTED_STRING_ESCAPED)
        {
          s += *i;
          state = QUOTED_STRING;
        }
      else if (*i == '#')
        {
          state = COMMENT;
        }
      else if (state == COMMENT)
        {
          // ignore comments
        }
      else
        {
          return false;
        }
    }
  return state == BLANK || state == COMMENT;
}

void
Key::load_key (const string& key_file)
{
  FILE *f = utf8_fopen(key_file, "rb");
  if (!f) throw EngineError("Cannot open key file: " + key_file);
  ScopedFile owner(f);
  std::string text;
  char buffer[4096];
  size_t n;
  while ((n = fread(buffer, 1, sizeof(buffer), f))) text.append(buffer, n);
  if (ferror(f)) throw EngineError("Cannot read key file: " + key_file);
  std::string name = key_file.substr(key_file.find_last_of("\\/") + 1);
  import_text(text, name);
}

void Key::import_text(const std::string& text, const std::string& default_name)
{
  std::istringstream input(text);
  std::string line;
  std::string name = default_name;
  std::vector<unsigned char> bytes;
  unsigned keys = 0, line_number = 0;
  while (std::getline(input, line)) {
    ++line_number;
    std::vector<std::string> tokens;
    if (!tokenize(line, tokens)) throw std::invalid_argument("Invalid key syntax at line " + std::to_string(line_number));
    if (tokens.empty()) continue;
    if (tokens.size() != 2) throw std::invalid_argument("Invalid key field at line " + std::to_string(line_number));
    if (tokens[0] == "key") {
      bytes = hex_str_to_vec(tokens[1]);
      if (++keys != 1 || bytes.size() != SIZE) throw std::invalid_argument("Key must contain exactly one 128-bit key");
    } else if (tokens[0] == "name") name = tokens[1];
    else throw std::invalid_argument("Unknown key field: " + tokens[0]);
  }
  if (keys != 1) throw std::invalid_argument("Key contains no key");
  m_aes_key = std::move(bytes);
  m_name = std::move(name);
}
std::string Key::export_text() const
{
  std::string escaped;
  for (char c : m_name) {
    if (c == '\\' || c == '"') escaped += '\\';
    escaped += c;
  }
  return "# watermarking key for audiowmark\n\nkey " + vec_to_hex_str(m_aes_key) + "\nname \"" + escaped + "\"\n";
}

const unsigned char *
Key::aes_key() const
{
  assert (m_aes_key.size() == SIZE);
  return m_aes_key.data();
}

const string&
Key::name() const
{
  return m_name;
}
