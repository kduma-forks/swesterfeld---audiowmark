/*
 * Copyright (C) 2020 Stefan Westerfeld
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

#include "threadpool.hh"
#include "utils.hh"

bool
ThreadPool::worker_next_job (Job& job)
{
  std::unique_lock<std::mutex> lock(mutex);
  cond.wait(lock, [&] { return stop_workers || !jobs.empty(); });
  if (jobs.empty()) return false;
  job = std::move(jobs.front());
  jobs.pop_front();
  return true;
}
void ThreadPool::worker_run()
{
  ConfigScope scope(config);
  Job job;
  while (worker_next_job(job)) {
    try { job.fun(); }
    catch (...) {
      std::lock_guard<std::mutex> lock(mutex);
      if (!failure) failure = std::current_exception();
    }
    job.fun = nullptr;
    {
      std::lock_guard<std::mutex> lock(mutex);
      ++jobs_done;
    }
    main_cond.notify_all();
  }
}
ThreadPool::ThreadPool() : config(params())
{
  unsigned count = config.workers ? config.workers : std::max(1u, std::thread::hardware_concurrency());
  try {
    for (unsigned i = 0; i < count; ++i)
      threads.emplace_back(&ThreadPool::worker_run, this);
  } catch (...) {
    { std::lock_guard<std::mutex> lock(mutex); stop_workers = true; }
    cond.notify_all();
    for (auto& thread : threads) thread.join();
    throw;
  }
}
void ThreadPool::add_job (std::function<void()> fun)
{
  std::lock_guard<std::mutex> lock(mutex);
  jobs.push_back(Job{std::move(fun)});
  ++jobs_added;
  cond.notify_one();
}
void ThreadPool::wait_all()
{
  std::unique_lock<std::mutex> lock(mutex);
  main_cond.wait(lock, [&] { return jobs_added == jobs_done; });
  auto exception = failure;
  failure = nullptr;
  lock.unlock();
  if (exception) std::rethrow_exception(exception);
}
size_t ThreadPool::n_threads() { return threads.size(); }
ThreadPool::~ThreadPool()
{
  // Drain jobs before joining, including during exception unwinding.
  { std::lock_guard<std::mutex> lock(mutex); stop_workers = true; }
  cond.notify_all();
  for (auto& thread : threads) thread.join();
}
