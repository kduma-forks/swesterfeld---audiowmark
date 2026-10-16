/* Process helper tests; add this program to the Automake test list. */

#include "config.h"
#include "process.hh"

#include <cstdio>
#include <csignal>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

#ifndef _WIN32
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#else
#include <windows.h>
#include <aclapi.h>
#include <fcntl.h>
#include <io.h>
#endif

using std::string;
using std::vector;

static void
require (bool condition, const char *message)
{
  if (!condition)
    {
      fprintf (stderr, "testprocess: %s\n", message);
      exit (1);
    }
}

static string
read_file (const string& filename)
{
  FILE *file = utf8_fopen (filename, "rb");
  require (file != nullptr, "cannot open test file for reading");
  string result;
  char buffer[128];
  size_t size;
  while ((size = fread (buffer, 1, sizeof (buffer), file)) != 0)
    result.append (buffer, size);
  require (!ferror (file), "cannot read test file");
  fclose (file);
  return result;
}

static void
write_file (const string& filename, const string& contents)
{
  FILE *file = utf8_fopen (filename, "wb");
  require (file != nullptr, "cannot open test file for writing");
  require (fwrite (contents.data(), 1, contents.size(), file) == contents.size(), "cannot write test file");
  require (fclose (file) == 0, "cannot close test file");
}

static bool
path_exists (const string& path)
{
#ifdef _WIN32
  try
    {
      return GetFileAttributesW (utf8_wide (path).c_str()) != INVALID_FILE_ATTRIBUTES;
    }
  catch (...)
    {
      return false;
    }
#else
  struct stat st;
  return stat (path.c_str(), &st) == 0;
#endif
}

#ifdef _WIN32
static void
require_private_directory (const string& path)
{
  PACL dacl = nullptr;
  PSECURITY_DESCRIPTOR descriptor = nullptr;
  DWORD status = GetNamedSecurityInfoW (const_cast<wchar_t *> (utf8_wide (path).c_str()), SE_FILE_OBJECT,
                                        DACL_SECURITY_INFORMATION, nullptr, nullptr, &dacl, nullptr, &descriptor);
  require (status == ERROR_SUCCESS && descriptor && dacl, "cannot read temporary directory DACL");
  SECURITY_DESCRIPTOR_CONTROL control = 0;
  DWORD revision = 0;
  require (GetSecurityDescriptorControl (descriptor, &control, &revision) && (control & SE_DACL_PROTECTED),
           "temporary directory DACL permits inherited access");
  require (dacl->AceCount == 1, "temporary directory DACL grants access to more than one principal");
  void *raw_ace = nullptr;
  require (GetAce (dacl, 0, &raw_ace), "cannot inspect temporary directory DACL");
  ACCESS_ALLOWED_ACE *ace = static_cast<ACCESS_ALLOWED_ACE *> (raw_ace);
  require (ace->Header.AceType == ACCESS_ALLOWED_ACE_TYPE &&
           (ace->Mask & FILE_ALL_ACCESS) == FILE_ALL_ACCESS,
           "temporary directory DACL does not grant its user full access");

  HANDLE token = nullptr;
  require (OpenProcessToken (GetCurrentProcess(), TOKEN_QUERY, &token), "cannot open process token");
  DWORD token_size = 0;
  GetTokenInformation (token, TokenUser, nullptr, 0, &token_size);
  vector<DWORD> token_buffer ((token_size + sizeof (DWORD) - 1) / sizeof (DWORD));
  require (token_size && GetTokenInformation (token, TokenUser, token_buffer.data(), token_size, &token_size),
           "cannot read process user SID");
  CloseHandle (token);
  PSID ace_sid = &ace->SidStart;
  PSID user_sid = reinterpret_cast<TOKEN_USER *> (token_buffer.data())->User.Sid;
  require (EqualSid (ace_sid, user_sid), "temporary directory DACL is not restricted to its user");
  LocalFree (descriptor);
}
#endif

int
main (int argc, char **argv)
{
#ifndef _WIN32
  if (argc > 1 && strcmp (argv[1], "sleep-child") == 0)
    {
      sleep (30);
      return 0;
    }
#endif
  if (argc > 1 && strcmp (argv[1], "child") == 0)
    {
      require (argc == 6, "child received the wrong number of arguments");
#ifdef _WIN32
      /* This fixture intentionally emits one CRLF line and one LF line. Avoid the
       * Windows CRT translating both '\n' bytes so Process::run sees those exact bytes.
       */
      require (_setmode (_fileno (stdout), _O_BINARY) != -1, "cannot set child stdout to binary mode");
#endif
      printf ("first\r\nsecond\n");
      printf ("%s|%s|%s", argv[2], argv[3], argv[4]);
      return atoi (argv[5]);
    }

  string temporary_path;
  {
    Process::TempDir temporary;
    Error err = temporary.create();
    require (!err, err.message());
    temporary_path = temporary.path();
    require (!temporary_path.empty(), "temporary directory path is empty");

#ifndef _WIN32
    struct stat mode;
    require (stat (temporary_path.c_str(), &mode) == 0, "cannot stat temporary directory");
    require ((mode.st_mode & 0777) == 0700, "temporary directory is not private");
#else
    require_private_directory (temporary_path);
#endif

    string nested = temporary.file ("nested");
    err = Process::make_directory (nested);
    require (!err, err.message());
    err = Process::make_directory (nested);
    require (!err, "creating an existing directory failed");

    const string unicode_file = temporary.file ("dźwięk-音.txt");
    write_file (unicode_file, "payload");
    require (Process::is_regular_file (unicode_file), "regular file was not detected");
    uint64_t size = 0;
    err = Process::file_size (unicode_file, size);
    require (!err && size == 7, "file size is wrong");
    require (Process::same_file (unicode_file, unicode_file), "same file was not identified");

    string replacement = temporary.file ("replacement.txt");
    write_file (replacement, "new");
    err = Process::replace_file (replacement, unicode_file);
    require (!err, err.message());
    require (read_file (unicode_file) == "new", "atomic replacement has wrong contents");
    require (!Process::is_regular_file (replacement), "replacement source still exists");

    string executable = Process::absolute_path (argv[0]);
    vector<string> lines;
    err = Process::run ({ executable, "child", "space value", "quote\"value", "trailing\\", "0" }, &lines);
    require (!err, err.message());
    require (lines.size() == 3, "captured stdout has the wrong line count");
    require (lines[0] == "first" && lines[1] == "second", "captured stdout line parsing failed");
    require (lines[2] == "space value|quote\"value|trailing\\", "process argument quoting failed");

    err = Process::run ({ executable, "child", "a", "b", "c", "23" });
    require (err, "non-zero process status was accepted");

    const string path_only_name = "audiowmark-path-only-helper";
#ifdef _WIN32
    string path_only_file = temporary.file (path_only_name + ".exe");
#else
    string path_only_file = temporary.file (path_only_name);
#endif
    write_file (path_only_file, "not executed");
#ifdef _WIN32
    require (SetEnvironmentVariableW (L"PATH", utf8_wide (temporary.path()).c_str()),
             "cannot set temporary PATH");
#else
    require (chmod (path_only_file.c_str(), 0700) == 0, "cannot make PATH-only tool executable");
    require (setenv ("PATH", temporary.path().c_str(), 1) == 0, "cannot set temporary PATH");
#endif
    string resolved_tool;
    err = Process::tool (path_only_name, resolved_tool);
#if AUDIOWMARK_BUNDLED_TOOLS
    require (err && resolved_tool.empty(), "bundled mode fell back to a PATH-only tool");
#else
    require (!err && Process::same_file (resolved_tool, path_only_file),
             "portable mode did not resolve the PATH-only tool");
#endif

#ifndef _WIN32
    /* A whole-operation guard owns the handler while temporary resources exist. Process::run
     * nests its own guard and must observe (not clear) a request made between child processes.
     */
    string interrupted_path;
    {
      Process::InterruptGuard operation;
      err = operation.init();
      require (!err, err.message());
      require (!operation.requested() && !operation.error(), "fresh interrupt guard is cancelled");

      Process::TempDir interrupted_temp;
      err = interrupted_temp.create();
      require (!err, err.message());
      interrupted_path = interrupted_temp.path();
      raise (SIGINT);
      require (operation.requested(), "operation guard did not record SIGINT");
      Error interrupt_error = operation.error();
      require (interrupt_error && strstr (interrupt_error.message(), "interrupted") != nullptr,
               "operation guard returned the wrong interruption error");

      Process::InterruptGuard nested;
      err = nested.init();
      require (!err && nested.requested(), "nested guard cleared the outer interruption");
      err = Process::run ({ temporary.file ("must-not-be-spawned") });
      require (err && strstr (err.message(), "interrupted") != nullptr,
               "runner attempted to spawn after an outer interruption");
    }
    require (!path_exists (interrupted_path), "interrupted operation did not unwind its temporary directory");

    pid_t signaler = fork();
    require (signaler >= 0, "cannot fork signal helper");
    if (signaler == 0)
      {
        usleep (100 * 1000);
        kill (getppid(), SIGTERM);
        _exit (0);
      }
    lines.clear();
    err = Process::run ({ executable, "sleep-child" }, &lines);
    require (err, "interrupted process was accepted");
    require (strstr (err.message(), "interrupted") != nullptr, "interruption returned the wrong error");
    int signaler_status = 0;
    require (waitpid (signaler, &signaler_status, 0) == signaler, "cannot wait for signal helper");
    require (WIFEXITED (signaler_status) && WEXITSTATUS (signaler_status) == 0,
             "runner terminated an unrelated child process");
#endif
  }

  require (!path_exists (temporary_path), "temporary directory cleanup failed");
  printf ("process helper tests passed\n");
  return 0;
}
