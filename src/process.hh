/*
 * Copyright (C) 2026 audiowmark contributors
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 */

#ifndef AUDIOWMARK_PROCESS_HH
#define AUDIOWMARK_PROCESS_HH

#include "utils.hh"

#include <cstdint>
#include <string>
#include <vector>

namespace Process {

/* A narrow, cooperative cancellation scope. The signal/console handler only records the
 * request; callers keep ordinary C++ unwinding and decide where it is safe to stop. Scopes may
 * be nested (Process::run creates one); a nested scope never clears an outer request.
 */
class InterruptGuard
{
public:
  InterruptGuard();
  ~InterruptGuard();

  InterruptGuard (const InterruptGuard&) = delete;
  InterruptGuard& operator= (const InterruptGuard&) = delete;

  Error init();
  Error error() const;
  bool requested() const;

private:
  bool m_initialized = false;
};

Error run (const std::vector<std::string>& argv, std::vector<std::string> *stdout_lines = nullptr);
Error tool (const std::string& name, std::string& resolved);

std::string absolute_path (const std::string& path);
bool same_file (const std::string& a, const std::string& b);
Error replace_file (const std::string& source, const std::string& destination);
Error make_directory (const std::string& path);
bool is_regular_file (const std::string& path);
Error file_size (const std::string& path, uint64_t& size);

class TempDir
{
public:
  TempDir();
  ~TempDir();

  TempDir (const TempDir&) = delete;
  TempDir& operator= (const TempDir&) = delete;

  Error create (const std::string& parent = "");
  std::string path() const;
  std::string file (const std::string& basename) const;

private:
  std::string m_path;
};

} // namespace Process

#endif /* AUDIOWMARK_PROCESS_HH */
