/*
 * Copyright (C) 2026 audiowmark contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

#include "config.h"
#include "process.hh"

#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

#ifdef _WIN32

#include <windows.h>
#include <aclapi.h>

#else

#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

extern char **environ;

#endif

using std::string;
using std::vector;

namespace {

string
join_path (const string& directory, const string& name)
{
  if (directory.empty())
    return name;
#ifdef _WIN32
  const char separator = '\\';
  if (directory.back() == '/' || directory.back() == '\\')
#else
  const char separator = '/';
  if (directory.back() == '/')
#endif
    return directory + name;
  return directory + separator + name;
}

void
append_output (const char *data, size_t size, string& pending, vector<string>& lines)
{
  pending.append (data, size);
  size_t start = 0;
  for (;;)
    {
      size_t newline = pending.find ('\n', start);
      if (newline == string::npos)
        {
          pending.erase (0, start);
          return;
        }
      string line = pending.substr (start, newline - start);
      if (!line.empty() && line.back() == '\r')
        line.pop_back();
      lines.push_back (line);
      start = newline + 1;
    }
}

#ifdef _WIN32

string
wide_utf8 (const std::wstring& text)
{
  if (text.empty())
    return string();
  int count = WideCharToMultiByte (CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), int (text.size()), nullptr, 0, nullptr, nullptr);
  if (count <= 0)
    return string();
  string result (size_t (count), '\0');
  if (!WideCharToMultiByte (CP_UTF8, WC_ERR_INVALID_CHARS, text.data(), int (text.size()), &result[0], count, nullptr, nullptr))
    return string();
  return result;
}

string
windows_error (const string& operation, DWORD code = GetLastError())
{
  wchar_t *message = nullptr;
  DWORD size = FormatMessageW (FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
                               FORMAT_MESSAGE_IGNORE_INSERTS, nullptr, code, 0,
                               reinterpret_cast<wchar_t *> (&message), 0, nullptr);
  std::wstring detail = size && message ? std::wstring (message, size) : std::wstring();
  if (message)
    LocalFree (message);
  while (!detail.empty() && (detail.back() == L'\r' || detail.back() == L'\n' || detail.back() == L' '))
    detail.pop_back();
  string utf8 = wide_utf8 (detail);
  if (utf8.empty())
    return string_printf ("%s failed (Windows error %lu)", operation.c_str(), static_cast<unsigned long> (code));
  return string_printf ("%s failed: %s (Windows error %lu)", operation.c_str(), utf8.c_str(),
                        static_cast<unsigned long> (code));
}

volatile LONG cancel_requested = 0;
unsigned cancellation_depth = 0;

BOOL WINAPI
console_control_handler (DWORD event)
{
  if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT || event == CTRL_CLOSE_EVENT ||
      event == CTRL_LOGOFF_EVENT || event == CTRL_SHUTDOWN_EVENT)
    {
      InterlockedCompareExchange (&cancel_requested, LONG (event + 1), 0);
      return TRUE;
    }
  return FALSE;
}

class WinHandle
{
public:
  WinHandle() = default;
  explicit WinHandle (HANDLE handle) : m_handle (handle) {}
  ~WinHandle() { reset(); }

  WinHandle (const WinHandle&) = delete;
  WinHandle& operator= (const WinHandle&) = delete;

  HANDLE get() const { return m_handle; }
  HANDLE release()
  {
    HANDLE handle = m_handle;
    m_handle = INVALID_HANDLE_VALUE;
    return handle;
  }
  void reset (HANDLE handle = INVALID_HANDLE_VALUE)
  {
    if (m_handle != INVALID_HANDLE_VALUE && m_handle != nullptr)
      CloseHandle (m_handle);
    m_handle = handle;
  }
  bool valid() const { return m_handle != INVALID_HANDLE_VALUE && m_handle != nullptr; }

private:
  HANDLE m_handle = INVALID_HANDLE_VALUE;
};

Error
private_directory_security (vector<DWORD>& token_buffer, vector<DWORD>& acl_buffer,
                            SECURITY_DESCRIPTOR& descriptor, SECURITY_ATTRIBUTES& attributes)
{
  HANDLE raw_token = INVALID_HANDLE_VALUE;
  if (!OpenProcessToken (GetCurrentProcess(), TOKEN_QUERY, &raw_token))
    return Error (windows_error ("OpenProcessToken"));
  WinHandle token (raw_token);

  DWORD token_size = 0;
  GetTokenInformation (token.get(), TokenUser, nullptr, 0, &token_size);
  if (!token_size || GetLastError() != ERROR_INSUFFICIENT_BUFFER)
    return Error (windows_error ("GetTokenInformation(size)"));
  token_buffer.resize ((token_size + sizeof (DWORD) - 1) / sizeof (DWORD));
  if (!GetTokenInformation (token.get(), TokenUser, token_buffer.data(), token_size, &token_size))
    return Error (windows_error ("GetTokenInformation"));
  PSID user_sid = reinterpret_cast<TOKEN_USER *> (token_buffer.data())->User.Sid;
  if (!IsValidSid (user_sid))
    return Error ("current Windows user has an invalid SID");

  DWORD acl_size = sizeof (ACL) + sizeof (ACCESS_ALLOWED_ACE) - sizeof (DWORD) + GetLengthSid (user_sid);
  acl_buffer.resize ((acl_size + sizeof (DWORD) - 1) / sizeof (DWORD));
  PACL acl = reinterpret_cast<PACL> (acl_buffer.data());
  if (!InitializeAcl (acl, acl_size, ACL_REVISION))
    return Error (windows_error ("InitializeAcl"));
  if (!AddAccessAllowedAceEx (acl, ACL_REVISION, OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE,
                              FILE_ALL_ACCESS, user_sid))
    return Error (windows_error ("AddAccessAllowedAceEx"));
  if (!InitializeSecurityDescriptor (&descriptor, SECURITY_DESCRIPTOR_REVISION))
    return Error (windows_error ("InitializeSecurityDescriptor"));
  if (!SetSecurityDescriptorDacl (&descriptor, TRUE, acl, FALSE))
    return Error (windows_error ("SetSecurityDescriptorDacl"));
  if (!SetSecurityDescriptorControl (&descriptor, SE_DACL_PROTECTED, SE_DACL_PROTECTED))
    return Error (windows_error ("SetSecurityDescriptorControl"));

  attributes.nLength = sizeof (attributes);
  attributes.lpSecurityDescriptor = &descriptor;
  attributes.bInheritHandle = FALSE;
  return Error::Code::NONE;
}

Error
duplicate_inheritable (DWORD standard_handle, WinHandle& duplicate)
{
  HANDLE source = GetStdHandle (standard_handle);
  if (source == INVALID_HANDLE_VALUE || source == nullptr)
    {
      HANDLE null_handle = CreateFileW (L"NUL", standard_handle == STD_INPUT_HANDLE ? GENERIC_READ : GENERIC_WRITE,
                                        FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                                        FILE_ATTRIBUTE_NORMAL, nullptr);
      if (null_handle == INVALID_HANDLE_VALUE)
        return Error (windows_error ("CreateFileW(NUL)"));
      WinHandle null_guard (null_handle);
      HANDLE inherited = INVALID_HANDLE_VALUE;
      if (!DuplicateHandle (GetCurrentProcess(), null_handle, GetCurrentProcess(), &inherited, 0, TRUE,
                            DUPLICATE_SAME_ACCESS))
        return Error (windows_error ("DuplicateHandle"));
      duplicate.reset (inherited);
      return Error::Code::NONE;
    }

  HANDLE inherited = INVALID_HANDLE_VALUE;
  if (!DuplicateHandle (GetCurrentProcess(), source, GetCurrentProcess(), &inherited, 0, TRUE,
                        DUPLICATE_SAME_ACCESS))
    return Error (windows_error ("DuplicateHandle"));
  duplicate.reset (inherited);
  return Error::Code::NONE;
}

std::wstring
quote_windows_argument (const std::wstring& argument)
{
  if (argument.find_first_of (L" \t\n\v\"") == std::wstring::npos && !argument.empty())
    return argument;

  std::wstring result = L"\"";
  size_t backslashes = 0;
  for (wchar_t character : argument)
    {
      if (character == L'\\')
        {
          backslashes++;
          continue;
        }
      if (character == L'\"')
        {
          result.append (backslashes * 2 + 1, L'\\');
          result.push_back (L'\"');
        }
      else
        {
          result.append (backslashes, L'\\');
          result.push_back (character);
        }
      backslashes = 0;
    }
  result.append (backslashes * 2, L'\\');
  result.push_back (L'\"');
  return result;
}

Error
module_filename (std::wstring& filename)
{
  for (DWORD capacity = 512; capacity <= 32768; capacity *= 2)
    {
      std::vector<wchar_t> buffer (capacity);
      DWORD size = GetModuleFileNameW (nullptr, buffer.data(), capacity);
      if (size == 0)
        return Error (windows_error ("GetModuleFileNameW"));
      if (size < capacity - 1)
        {
          filename.assign (buffer.data(), size);
          return Error::Code::NONE;
        }
    }
  return Error ("executable path exceeds Windows path limit");
}

bool
windows_file_info (const string& path, BY_HANDLE_FILE_INFORMATION& info)
{
  std::wstring wide;
  try
    {
      wide = utf8_wide (path);
    }
  catch (...)
    {
      return false;
    }
  WinHandle handle (CreateFileW (wide.c_str(), 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                 nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr));
  return handle.valid() && GetFileInformationByHandle (handle.get(), &info);
}

void
remove_tree (const std::wstring& directory)
{
  WIN32_FIND_DATAW data;
  HANDLE raw_find = FindFirstFileW ((directory + L"\\*").c_str(), &data);
  if (raw_find != INVALID_HANDLE_VALUE)
    {
      do
        {
          if (wcscmp (data.cFileName, L".") == 0 || wcscmp (data.cFileName, L"..") == 0)
            continue;
          std::wstring child = directory + L"\\" + data.cFileName;
          if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) &&
              !(data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT))
            remove_tree (child);
          else if (data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)
            RemoveDirectoryW (child.c_str());
          else
            {
              if (data.dwFileAttributes & FILE_ATTRIBUTE_READONLY)
                SetFileAttributesW (child.c_str(), data.dwFileAttributes & ~FILE_ATTRIBUTE_READONLY);
              DeleteFileW (child.c_str());
            }
        }
      while (FindNextFileW (raw_find, &data));
      FindClose (raw_find);
    }
  RemoveDirectoryW (directory.c_str());
}

#else

string
posix_error (const string& operation, int code = errno)
{
  return string_printf ("%s failed: %s", operation.c_str(), strerror (code));
}

volatile sig_atomic_t cancel_requested = 0;
unsigned cancellation_depth = 0;
struct sigaction previous_sigint = {};
struct sigaction previous_sigterm = {};

extern "C" void
cancellation_handler (int signal_number)
{
  if (!cancel_requested)
    cancel_requested = signal_number;
}

pid_t
wait_for_child (pid_t pid, int& status, const Process::InterruptGuard& cancellation)
{
  bool terminated = false;
  int terminate_polls = 0;
  for (;;)
    {
      if (cancellation.requested() && !terminated)
        {
          if (kill (pid, SIGTERM) != 0 && errno != ESRCH)
            return -1;
          terminated = true;
        }

      pid_t waited = waitpid (pid, &status, WNOHANG);
      if (waited > 0)
        return waited;
      if (waited < 0)
        {
          if (errno == EINTR)
            continue;
          return -1;
        }

      if (terminated && ++terminate_polls > 40)
        {
          if (kill (pid, SIGKILL) != 0 && errno != ESRCH)
            return -1;
          do
            waited = waitpid (pid, &status, 0);
          while (waited < 0 && errno == EINTR);
          return waited;
        }

      struct timespec delay = { 0, 50 * 1000 * 1000 };
      while (nanosleep (&delay, &delay) != 0 && errno == EINTR && !cancellation.requested())
        {
        }
    }
}

class FileDescriptor
{
public:
  FileDescriptor() = default;
  explicit FileDescriptor (int fd) : m_fd (fd) {}
  ~FileDescriptor() { reset(); }

  FileDescriptor (const FileDescriptor&) = delete;
  FileDescriptor& operator= (const FileDescriptor&) = delete;

  int get() const { return m_fd; }
  int release()
  {
    int fd = m_fd;
    m_fd = -1;
    return fd;
  }
  void reset (int fd = -1)
  {
    if (m_fd >= 0)
      close (m_fd);
    m_fd = fd;
  }
  bool valid() const { return m_fd >= 0; }

private:
  int m_fd = -1;
};

Error
set_close_on_exec (int fd)
{
  int flags;
  do
    flags = fcntl (fd, F_GETFD);
  while (flags < 0 && errno == EINTR);
  if (flags < 0)
    return Error (posix_error ("fcntl(F_GETFD)"));
  int result;
  do
    result = fcntl (fd, F_SETFD, flags | FD_CLOEXEC);
  while (result < 0 && errno == EINTR);
  if (result < 0)
    return Error (posix_error ("fcntl(F_SETFD)"));
  return Error::Code::NONE;
}

Error
executable_filename (string& filename)
{
#if defined(__linux__) || defined(__CYGWIN__)
  vector<char> buffer (512);
  for (;;)
    {
      ssize_t size = readlink ("/proc/self/exe", buffer.data(), buffer.size());
      if (size < 0)
        return Error (posix_error ("readlink(/proc/self/exe)"));
      if (size_t (size) < buffer.size())
        {
          filename.assign (buffer.data(), size_t (size));
          return Error::Code::NONE;
        }
      if (buffer.size() >= 1024 * 1024)
        return Error ("executable path is too long");
      buffer.resize (buffer.size() * 2);
    }
#elif defined(__APPLE__)
  uint32_t size = 0;
  _NSGetExecutablePath (nullptr, &size);
  vector<char> buffer (size + 1);
  if (_NSGetExecutablePath (buffer.data(), &size) != 0)
    return Error ("_NSGetExecutablePath failed");
  char *canonical = realpath (buffer.data(), nullptr);
  if (!canonical)
    return Error (posix_error ("realpath(executable)"));
  filename = canonical;
  free (canonical);
  return Error::Code::NONE;
#else
  (void) filename;
  return Error ("cannot determine executable path on this platform");
#endif
}

void
remove_tree (const string& directory)
{
  DIR *dir = opendir (directory.c_str());
  if (dir)
    {
      for (;;)
        {
          errno = 0;
          struct dirent *entry = readdir (dir);
          if (!entry)
            break;
          if (strcmp (entry->d_name, ".") == 0 || strcmp (entry->d_name, "..") == 0)
            continue;
          string child = join_path (directory, entry->d_name);
          struct stat st;
          if (lstat (child.c_str(), &st) == 0 && S_ISDIR (st.st_mode))
            remove_tree (child);
          else
            unlink (child.c_str());
        }
      closedir (dir);
    }
  rmdir (directory.c_str());
}

#endif

} // anonymous namespace

namespace Process {

InterruptGuard::InterruptGuard() = default;

InterruptGuard::~InterruptGuard()
{
  if (!m_initialized)
    return;

  if (cancellation_depth == 0)
    return; // defensive: never underflow if platform state was damaged
  cancellation_depth--;
  if (cancellation_depth != 0)
    return;

#ifdef _WIN32
  SetConsoleCtrlHandler (console_control_handler, FALSE);
#else
  sigaction (SIGTERM, &previous_sigterm, nullptr);
  sigaction (SIGINT, &previous_sigint, nullptr);
#endif
}

Error
InterruptGuard::init()
{
  if (m_initialized)
    return Error ("interrupt guard was already initialized");

  if (cancellation_depth == 0)
    {
#ifdef _WIN32
      InterlockedExchange (&cancel_requested, 0);
      if (!SetConsoleCtrlHandler (console_control_handler, TRUE))
        return Error (windows_error ("SetConsoleCtrlHandler"));
#else
      cancel_requested = 0;
      struct sigaction action = {};
      action.sa_handler = cancellation_handler;
      sigemptyset (&action.sa_mask);
      action.sa_flags = 0; // Interrupt blocking calls; cleanup remains in ordinary control flow.
      if (sigaction (SIGINT, &action, &previous_sigint) != 0)
        return Error (posix_error ("sigaction(SIGINT)"));
      if (sigaction (SIGTERM, &action, &previous_sigterm) != 0)
        {
          const int saved_errno = errno;
          sigaction (SIGINT, &previous_sigint, nullptr);
          return Error (posix_error ("sigaction(SIGTERM)", saved_errno));
        }
#endif
    }

  cancellation_depth++;
  m_initialized = true;
  return Error::Code::NONE;
}

bool
InterruptGuard::requested() const
{
#ifdef _WIN32
  return InterlockedCompareExchange (&cancel_requested, 0, 0) != 0;
#else
  return cancel_requested != 0;
#endif
}

Error
InterruptGuard::error() const
{
  if (!requested())
    return Error::Code::NONE;
#ifdef _WIN32
  const LONG event = InterlockedCompareExchange (&cancel_requested, 0, 0) - 1;
  return Error (string_printf ("operation was interrupted by console event %lu",
                               static_cast<unsigned long> (event)));
#else
  return Error (string_printf ("operation was interrupted by signal %d", int (cancel_requested)));
#endif
}

Error
run (const vector<string>& argv, vector<string> *stdout_lines)
{
  if (argv.empty() || argv[0].empty())
    return Error ("cannot execute an empty command");
  for (const auto& argument : argv)
    if (argument.find ('\0') != string::npos)
      return Error ("process argument contains a NUL byte");

  if (stdout_lines)
    stdout_lines->clear();

  InterruptGuard cancellation;
  Error cancellation_error = cancellation.init();
  if (cancellation_error)
    return cancellation_error;
  if (cancellation.requested())
    return cancellation.error();

#ifdef _WIN32
  std::vector<std::wstring> wide_arguments;
  try
    {
      for (const auto& argument : argv)
        wide_arguments.push_back (utf8_wide (argument));
    }
  catch (const std::exception& exception)
    {
      return Error (string_printf ("invalid UTF-8 process argument: %s", exception.what()));
    }
  if (cancellation.requested())
    return cancellation.error();

  std::wstring command_line;
  for (size_t i = 0; i < wide_arguments.size(); i++)
    {
      if (i)
        command_line.push_back (L' ');
      command_line += quote_windows_argument (wide_arguments[i]);
    }
  std::vector<wchar_t> mutable_command (command_line.begin(), command_line.end());
  mutable_command.push_back (L'\0');

  WinHandle child_stdin;
  WinHandle child_stdout;
  WinHandle child_stderr;
  Error err = duplicate_inheritable (STD_INPUT_HANDLE, child_stdin);
  if (err)
    return err;
  err = duplicate_inheritable (STD_ERROR_HANDLE, child_stderr);
  if (err)
    return err;

  WinHandle pipe_read;
  if (stdout_lines)
    {
      SECURITY_ATTRIBUTES security = { sizeof (security), nullptr, TRUE };
      HANDLE read_handle = INVALID_HANDLE_VALUE;
      HANDLE write_handle = INVALID_HANDLE_VALUE;
      if (!CreatePipe (&read_handle, &write_handle, &security, 0))
        return Error (windows_error ("CreatePipe"));
      pipe_read.reset (read_handle);
      child_stdout.reset (write_handle);
      if (!SetHandleInformation (pipe_read.get(), HANDLE_FLAG_INHERIT, 0))
        return Error (windows_error ("SetHandleInformation"));
    }
  else
    {
      err = duplicate_inheritable (STD_OUTPUT_HANDLE, child_stdout);
      if (err)
        return err;
    }

  HANDLE inherited[] = { child_stdin.get(), child_stdout.get(), child_stderr.get() };
  SIZE_T attributes_size = 0;
  InitializeProcThreadAttributeList (nullptr, 1, 0, &attributes_size);
  if (!attributes_size && GetLastError() != ERROR_INSUFFICIENT_BUFFER)
    return Error (windows_error ("InitializeProcThreadAttributeList"));
  vector<unsigned char> attributes_buffer (attributes_size);
  auto attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST> (attributes_buffer.data());
  if (!InitializeProcThreadAttributeList (attributes, 1, 0, &attributes_size))
    return Error (windows_error ("InitializeProcThreadAttributeList"));
  struct AttributeGuard
  {
    LPPROC_THREAD_ATTRIBUTE_LIST attributes;
    ~AttributeGuard() { DeleteProcThreadAttributeList (attributes); }
  } attribute_guard { attributes };
  if (!UpdateProcThreadAttribute (attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                                  inherited, sizeof (inherited), nullptr, nullptr))
    return Error (windows_error ("UpdateProcThreadAttribute"));

  STARTUPINFOEXW startup = {};
  startup.StartupInfo.cb = sizeof (startup);
  startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
  startup.StartupInfo.hStdInput = child_stdin.get();
  startup.StartupInfo.hStdOutput = child_stdout.get();
  startup.StartupInfo.hStdError = child_stderr.get();
  startup.lpAttributeList = attributes;

  PROCESS_INFORMATION process = {};
  if (cancellation.requested())
    return cancellation.error();
  if (!CreateProcessW (wide_arguments[0].c_str(), mutable_command.data(), nullptr, nullptr, TRUE,
                       EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT, nullptr, nullptr,
                       &startup.StartupInfo, &process))
    return Error (windows_error (string_printf ("CreateProcessW(%s)", argv[0].c_str())));
  WinHandle process_handle (process.hProcess);
  WinHandle thread_handle (process.hThread);

  // The parent must release every child-side pipe/standard handle immediately;
  // otherwise EOF on captured stdout can never be observed.
  child_stdin.reset();
  child_stdout.reset();
  child_stderr.reset();

  bool child_terminated = false;
  auto cancel_child = [&] {
    if (cancellation.requested() && !child_terminated)
      {
        // Terminate only the process created by this invocation. Never use a
        // job-wide or console-wide termination primitive here.
        if (!TerminateProcess (process_handle.get(), 130) && GetLastError() != ERROR_ACCESS_DENIED)
          return Error (windows_error ("TerminateProcess"));
        child_terminated = true;
      }
    return Error (Error::Code::NONE);
  };

  Error read_error;
  if (stdout_lines)
    {
      string pending;
      char buffer[4096];
      for (;;)
        {
          Error cancel_error = cancel_child();
          if (cancel_error)
            {
              read_error = cancel_error;
              break;
            }
          DWORD available = 0;
          if (!PeekNamedPipe (pipe_read.get(), nullptr, 0, nullptr, &available, nullptr))
            {
              DWORD code = GetLastError();
              if (code != ERROR_BROKEN_PIPE)
                read_error = Error (windows_error ("PeekNamedPipe(process stdout)", code));
              break;
            }
          if (available)
            {
              DWORD count = 0;
              DWORD request = std::min<DWORD> (available, sizeof (buffer));
              if (!ReadFile (pipe_read.get(), buffer, request, &count, nullptr))
                {
                  DWORD code = GetLastError();
                  if (code != ERROR_BROKEN_PIPE)
                    read_error = Error (windows_error ("ReadFile(process stdout)", code));
                  break;
                }
              if (count)
                append_output (buffer, count, pending, *stdout_lines);
              continue;
            }
          DWORD wait_result = WaitForSingleObject (process_handle.get(), 50);
          if (wait_result != WAIT_OBJECT_0 && wait_result != WAIT_TIMEOUT)
            {
              read_error = Error (windows_error ("WaitForSingleObject"));
              break;
            }
        }
      if (!pending.empty())
        stdout_lines->push_back (pending);
      pipe_read.reset();
    }

  for (;;)
    {
      Error cancel_error = cancel_child();
      if (cancel_error)
        return cancel_error;
      DWORD wait_result = WaitForSingleObject (process_handle.get(), 50);
      if (wait_result == WAIT_OBJECT_0)
        break;
      if (wait_result != WAIT_TIMEOUT)
        return Error (windows_error ("WaitForSingleObject"));
    }
  DWORD exit_code = 0;
  if (!GetExitCodeProcess (process_handle.get(), &exit_code))
    return Error (windows_error ("GetExitCodeProcess"));
  if (read_error)
    return read_error;
  if (cancellation.requested())
    return cancellation.error();
  if (exit_code != 0)
    return Error (string_printf ("process '%s' exited with status %lu", argv[0].c_str(),
                                 static_cast<unsigned long> (exit_code)));
  return Error::Code::NONE;

#else
  FileDescriptor pipe_read;
  FileDescriptor pipe_write;
  if (stdout_lines)
    {
      int fds[2];
      if (pipe (fds) != 0)
        return Error (posix_error ("pipe"));
      pipe_read.reset (fds[0]);
      pipe_write.reset (fds[1]);
      Error err = set_close_on_exec (pipe_read.get());
      if (err)
        return err;
      err = set_close_on_exec (pipe_write.get());
      if (err)
        return err;
    }

  posix_spawn_file_actions_t actions;
  int spawn_error = posix_spawn_file_actions_init (&actions);
  if (spawn_error)
    return Error (posix_error ("posix_spawn_file_actions_init", spawn_error));
  struct ActionsGuard
  {
    posix_spawn_file_actions_t *actions;
    ~ActionsGuard() { posix_spawn_file_actions_destroy (actions); }
  } actions_guard { &actions };

  if (stdout_lines)
    {
      spawn_error = posix_spawn_file_actions_addclose (&actions, pipe_read.get());
      if (!spawn_error)
        spawn_error = posix_spawn_file_actions_adddup2 (&actions, pipe_write.get(), STDOUT_FILENO);
      if (!spawn_error)
        spawn_error = posix_spawn_file_actions_addclose (&actions, pipe_write.get());
      if (spawn_error)
        return Error (posix_error ("posix_spawn_file_actions", spawn_error));
    }

  vector<char *> child_argv;
  child_argv.reserve (argv.size() + 1);
  for (const auto& argument : argv)
    child_argv.push_back (const_cast<char *> (argument.c_str()));
  child_argv.push_back (nullptr);

  if (cancellation.requested())
    return cancellation.error();

  pid_t pid = -1;
  spawn_error = posix_spawnp (&pid, child_argv[0], stdout_lines ? &actions : nullptr,
                              nullptr, child_argv.data(), environ);
  if (spawn_error)
    return Error (posix_error (string_printf ("posix_spawnp(%s)", argv[0].c_str()), spawn_error));

  // Only the spawned child owns this descriptor after posix_spawnp succeeds.
  pipe_write.reset();

  Error read_error;
  if (stdout_lines)
    {
      string pending;
      char buffer[4096];
      for (;;)
        {
          if (cancellation.requested())
            break;
          struct pollfd descriptor = { pipe_read.get(), POLLIN, 0 };
          int ready;
          do
            ready = poll (&descriptor, 1, 50);
          while (ready < 0 && errno == EINTR && !cancellation.requested());
          if (cancellation.requested())
            break;
          if (ready < 0)
            {
              read_error = Error (posix_error ("poll(process stdout)"));
              break;
            }
          if (ready == 0)
            continue;
          if (descriptor.revents & (POLLERR | POLLNVAL))
            {
              read_error = Error ("poll(process stdout) reported a descriptor error");
              break;
            }
          ssize_t count = read (pipe_read.get(), buffer, sizeof (buffer));
          if (count > 0)
            append_output (buffer, size_t (count), pending, *stdout_lines);
          else if (count == 0)
            break;
          else if (errno != EINTR)
            {
              read_error = Error (posix_error ("read(process stdout)"));
              break;
            }
        }
      if (!pending.empty())
        stdout_lines->push_back (pending);
      pipe_read.reset();
    }

  int status = 0;
  pid_t waited = wait_for_child (pid, status, cancellation);
  if (waited < 0)
    return Error (posix_error ("waitpid"));
  if (read_error)
    return read_error;
  if (cancellation.requested())
    return cancellation.error();
  if (WIFEXITED (status) && WEXITSTATUS (status) == 0)
    return Error::Code::NONE;
  if (WIFEXITED (status))
    return Error (string_printf ("process '%s' exited with status %d", argv[0].c_str(), WEXITSTATUS (status)));
  if (WIFSIGNALED (status))
    return Error (string_printf ("process '%s' terminated by signal %d", argv[0].c_str(), WTERMSIG (status)));
  return Error (string_printf ("process '%s' did not exit normally", argv[0].c_str()));
#endif
}

string
absolute_path (const string& path)
{
  if (path.empty())
    return string();
#ifdef _WIN32
  try
    {
      std::wstring wide = utf8_wide (path);
      DWORD required = GetFullPathNameW (wide.c_str(), 0, nullptr, nullptr);
      if (!required)
        return path;
      vector<wchar_t> buffer (required + 1);
      DWORD size = GetFullPathNameW (wide.c_str(), DWORD (buffer.size()), buffer.data(), nullptr);
      if (!size || size >= buffer.size())
        return path;
      string result = wide_utf8 (std::wstring (buffer.data(), size));
      return result.empty() ? path : result;
    }
  catch (...)
    {
      return path;
    }
#else
  if (path[0] == '/')
    return path;
  vector<char> cwd (256);
  while (!getcwd (cwd.data(), cwd.size()))
    {
      if (errno != ERANGE || cwd.size() >= 1024 * 1024)
        return path;
      cwd.resize (cwd.size() * 2);
    }
  return join_path (cwd.data(), path);
#endif
}

Error
tool (const string& name, string& resolved)
{
  resolved.clear();
  if (name.empty() || name.find ('/') != string::npos || name.find ('\\') != string::npos)
    return Error ("tool name must be a non-empty basename");

#ifdef _WIN32
  std::wstring executable;
  Error executable_error = module_filename (executable);
  if (executable_error)
    return executable_error;
  size_t separator = executable.find_last_of (L"/\\");
  if (separator == std::wstring::npos)
    return Error ("executable path has no directory");
  std::wstring tool_name;
  try
    {
      tool_name = utf8_wide (name);
    }
  catch (const std::exception& exception)
    {
      return Error (string_printf ("invalid UTF-8 tool name: %s", exception.what()));
    }
  if (tool_name.size() < 4 || _wcsicmp (tool_name.c_str() + tool_name.size() - 4, L".exe") != 0)
    tool_name += L".exe";
  std::wstring sibling = executable.substr (0, separator + 1) + tool_name;
  string sibling_utf8 = wide_utf8 (sibling);
  if (is_regular_file (sibling_utf8))
    {
      resolved = absolute_path (sibling_utf8);
      return Error::Code::NONE;
    }
#if AUDIOWMARK_BUNDLED_TOOLS
  return Error (string_printf ("required bundled tool '%s' is missing beside audiowmark", name.c_str()));
#else
  DWORD path_size = GetEnvironmentVariableW (L"PATH", nullptr, 0);
  std::wstring path_value;
  if (path_size)
    {
      vector<wchar_t> path_buffer (path_size);
      DWORD copied = GetEnvironmentVariableW (L"PATH", path_buffer.data(), path_size);
      if (copied && copied < path_size)
        path_value.assign (path_buffer.data(), copied);
    }
  size_t begin = 0;
  while (begin <= path_value.size())
    {
      size_t end = path_value.find (L';', begin);
      if (end == std::wstring::npos)
        end = path_value.size();
      std::wstring directory = path_value.substr (begin, end - begin);
      if (directory.size() >= 2 && directory.front() == L'\"' && directory.back() == L'\"')
        directory = directory.substr (1, directory.size() - 2);
      std::wstring candidate = directory.empty() ? tool_name : directory + L"\\" + tool_name;
      string candidate_utf8 = wide_utf8 (candidate);
      if (!candidate_utf8.empty() && is_regular_file (candidate_utf8))
        {
          resolved = absolute_path (candidate_utf8);
          return Error::Code::NONE;
        }
      if (end == path_value.size())
        break;
      begin = end + 1;
    }
  return Error (string_printf ("tool '%s' was not found beside audiowmark or on PATH", name.c_str()));
#endif

#else
  string executable;
  Error executable_error = executable_filename (executable);
  if (!executable_error)
    {
      size_t separator = executable.find_last_of ('/');
      if (separator == string::npos)
        executable_error = Error ("executable path has no directory");
      else
        {
          string sibling = executable.substr (0, separator + 1) + name;
          if (is_regular_file (sibling) && access (sibling.c_str(), X_OK) == 0)
            {
              resolved = absolute_path (sibling);
              return Error::Code::NONE;
            }
        }
    }
#if AUDIOWMARK_BUNDLED_TOOLS
  if (executable_error)
    return executable_error;
  return Error (string_printf ("required bundled tool '%s' is missing beside audiowmark", name.c_str()));
#else
  /* Portable builds historically allow PATH helpers. Failure to discover this executable's
   * directory on a generic Unix must not disable that fallback (notably for Cygwin variants).
   */
  const char *path_env = getenv ("PATH");
  string path_value = path_env ? path_env : "";
  size_t begin = 0;
  while (begin <= path_value.size())
    {
      size_t end = path_value.find (':', begin);
      if (end == string::npos)
        end = path_value.size();
      string directory = path_value.substr (begin, end - begin);
      string candidate = directory.empty() ? name : join_path (directory, name);
      if (is_regular_file (candidate) && access (candidate.c_str(), X_OK) == 0)
        {
          resolved = absolute_path (candidate);
          return Error::Code::NONE;
        }
      if (end == path_value.size())
        break;
      begin = end + 1;
    }
  return Error (string_printf ("tool '%s' was not found beside audiowmark or on PATH", name.c_str()));
#endif
#endif
}

bool
same_file (const string& a, const string& b)
{
#ifdef _WIN32
  BY_HANDLE_FILE_INFORMATION a_info = {};
  BY_HANDLE_FILE_INFORMATION b_info = {};
  return windows_file_info (a, a_info) && windows_file_info (b, b_info) &&
         a_info.dwVolumeSerialNumber == b_info.dwVolumeSerialNumber &&
         a_info.nFileIndexHigh == b_info.nFileIndexHigh &&
         a_info.nFileIndexLow == b_info.nFileIndexLow;
#else
  struct stat a_stat;
  struct stat b_stat;
  return stat (a.c_str(), &a_stat) == 0 && stat (b.c_str(), &b_stat) == 0 &&
         a_stat.st_dev == b_stat.st_dev && a_stat.st_ino == b_stat.st_ino;
#endif
}

Error
replace_file (const string& source, const string& destination)
{
  /* Publishing is the irreversible boundary for staged output. A surrounding operation guard
   * keeps a request pending; this nested checkpoint must not clear it.
   */
  InterruptGuard cancellation;
  Error cancellation_error = cancellation.init();
  if (cancellation_error)
    return cancellation_error;
  if (cancellation.requested())
    return cancellation.error();

#ifdef _WIN32
  try
    {
      std::wstring source_wide = utf8_wide (source);
      std::wstring destination_wide = utf8_wide (destination);
      if (!MoveFileExW (source_wide.c_str(), destination_wide.c_str(),
                        MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        return Error (windows_error ("MoveFileExW"));
      return Error::Code::NONE;
    }
  catch (const std::exception& exception)
    {
      return Error (string_printf ("invalid UTF-8 path: %s", exception.what()));
    }
#else
  if (rename (source.c_str(), destination.c_str()) != 0)
    return Error (posix_error ("rename"));
  return Error::Code::NONE;
#endif
}

Error
make_directory (const string& path)
{
  if (path.empty())
    return Error ("cannot create an empty directory path");
#ifdef _WIN32
  try
    {
      std::wstring wide = utf8_wide (path);
      if (CreateDirectoryW (wide.c_str(), nullptr))
        return Error::Code::NONE;
      DWORD code = GetLastError();
      if (code == ERROR_ALREADY_EXISTS)
        {
          DWORD attributes = GetFileAttributesW (wide.c_str());
          if (attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY))
            return Error::Code::NONE;
        }
      return Error (windows_error ("CreateDirectoryW", code));
    }
  catch (const std::exception& exception)
    {
      return Error (string_printf ("invalid UTF-8 directory path: %s", exception.what()));
    }
#else
  if (mkdir (path.c_str(), 0777) == 0)
    return Error::Code::NONE;
  if (errno == EEXIST)
    {
      struct stat st;
      if (stat (path.c_str(), &st) == 0 && S_ISDIR (st.st_mode))
        return Error::Code::NONE;
    }
  return Error (posix_error ("mkdir"));
#endif
}

bool
is_regular_file (const string& path)
{
#ifdef _WIN32
  BY_HANDLE_FILE_INFORMATION info = {};
  return windows_file_info (path, info) && !(info.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY);
#else
  struct stat st;
  return stat (path.c_str(), &st) == 0 && S_ISREG (st.st_mode);
#endif
}

Error
file_size (const string& path, uint64_t& size)
{
  size = 0;
#ifdef _WIN32
  try
    {
      std::wstring wide = utf8_wide (path);
      WinHandle handle (CreateFileW (wide.c_str(), GENERIC_READ,
                                     FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                                     nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
      if (!handle.valid())
        return Error (windows_error ("CreateFileW"));
      LARGE_INTEGER value;
      if (!GetFileSizeEx (handle.get(), &value))
        return Error (windows_error ("GetFileSizeEx"));
      if (value.QuadPart < 0)
        return Error ("file has a negative size");
      size = static_cast<uint64_t> (value.QuadPart);
      return Error::Code::NONE;
    }
  catch (const std::exception& exception)
    {
      return Error (string_printf ("invalid UTF-8 file path: %s", exception.what()));
    }
#else
  struct stat st;
  if (stat (path.c_str(), &st) != 0)
    return Error (posix_error ("stat"));
  if (st.st_size < 0)
    return Error ("file has a negative size");
  size = static_cast<uint64_t> (st.st_size);
  return Error::Code::NONE;
#endif
}

TempDir::TempDir() = default;

TempDir::~TempDir()
{
  if (m_path.empty())
    return;
#ifdef _WIN32
  try
    {
      remove_tree (utf8_wide (m_path));
    }
  catch (...)
    {
    }
#else
  remove_tree (m_path);
#endif
}

Error
TempDir::create (const string& parent)
{
  if (!m_path.empty())
    return Error ("temporary directory was already created");

#ifdef _WIN32
  std::wstring parent_wide;
  try
    {
      if (parent.empty())
        {
          DWORD required = GetTempPathW (0, nullptr);
          if (!required)
            return Error (windows_error ("GetTempPathW"));
          vector<wchar_t> buffer (required + 1);
          DWORD size = GetTempPathW (DWORD (buffer.size()), buffer.data());
          if (!size || size >= buffer.size())
            return Error (windows_error ("GetTempPathW"));
          parent_wide.assign (buffer.data(), size);
        }
      else
        parent_wide = utf8_wide (parent);
    }
  catch (const std::exception& exception)
    {
      return Error (string_printf ("invalid UTF-8 temporary path: %s", exception.what()));
    }
  while (parent_wide.size() > 1 && (parent_wide.back() == L'\\' || parent_wide.back() == L'/'))
    parent_wide.pop_back();

  vector<DWORD> token_buffer;
  vector<DWORD> acl_buffer;
  SECURITY_DESCRIPTOR descriptor;
  SECURITY_ATTRIBUTES security = {};
  Error security_error = private_directory_security (token_buffer, acl_buffer, descriptor, security);
  if (security_error)
    return security_error;

  HMODULE bcrypt = LoadLibraryW (L"bcrypt.dll");
  if (!bcrypt)
    return Error (windows_error ("LoadLibraryW(bcrypt.dll)"));
  struct LibraryGuard
  {
    HMODULE module;
    ~LibraryGuard() { FreeLibrary (module); }
  } library_guard { bcrypt };
  typedef LONG (WINAPI *GenRandomFn) (void *, unsigned char *, unsigned long, unsigned long);
  FARPROC random_proc = GetProcAddress (bcrypt, "BCryptGenRandom");
  if (!random_proc)
    return Error (windows_error ("GetProcAddress(BCryptGenRandom)"));
  static_assert (sizeof (random_proc) == sizeof (GenRandomFn), "Windows function pointer size mismatch");
  GenRandomFn gen_random;
  memcpy (&gen_random, &random_proc, sizeof (gen_random));

  for (int attempt = 0; attempt < 128; attempt++)
    {
      unsigned char random[16];
      // BCRYPT_USE_SYSTEM_PREFERRED_RNG is available on Windows Vista and later.
      if (gen_random (nullptr, random, sizeof (random), 0x00000002UL) < 0)
        return Error ("BCryptGenRandom failed");
      wchar_t name[64];
      _snwprintf (name, sizeof (name) / sizeof (name[0]),
                  L"audiowmark-%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x",
                  random[0], random[1], random[2], random[3], random[4], random[5], random[6], random[7],
                  random[8], random[9], random[10], random[11], random[12], random[13], random[14], random[15]);
      std::wstring candidate = parent_wide + L"\\" + name;
      if (CreateDirectoryW (candidate.c_str(), &security))
        {
          m_path = wide_utf8 (candidate);
          if (m_path.empty())
            {
              RemoveDirectoryW (candidate.c_str());
              return Error ("failed to encode temporary directory path as UTF-8");
            }
          return Error::Code::NONE;
        }
      DWORD code = GetLastError();
      if (code != ERROR_ALREADY_EXISTS && code != ERROR_FILE_EXISTS)
        return Error (windows_error ("CreateDirectoryW(temporary directory)", code));
    }
  return Error ("could not allocate a unique temporary directory");

#else
  string directory = parent;
  if (directory.empty())
    {
      const char *tmpdir = getenv ("TMPDIR");
      directory = tmpdir && tmpdir[0] ? tmpdir : "/tmp";
    }
  string pattern = join_path (directory, "audiowmark-XXXXXX");
  vector<char> buffer (pattern.begin(), pattern.end());
  buffer.push_back ('\0');
  char *created = mkdtemp (buffer.data());
  if (!created)
    return Error (posix_error ("mkdtemp"));
  m_path = created;
  return Error::Code::NONE;
#endif
}

string
TempDir::path() const
{
  return m_path;
}

string
TempDir::file (const string& basename) const
{
  return join_path (m_path, basename);
}

} // namespace Process
