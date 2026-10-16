/* Thread-pool synchronization, configuration inheritance and exception regressions. */
#include "threadpool.hh"
#include <atomic>
#include <stdexcept>
#include <iostream>

static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
int main() {
  try {
    EngineConfig config; config.workers = 2; config.water_delta = .023; config.quiet = true;
    ConfigScope scope(config);
    std::atomic<unsigned> done{0};
    {
      ThreadPool pool;
      check(pool.n_threads() == 2, "worker limit");
      for (unsigned round = 0; round < 20; ++round) {
        for (unsigned i = 0; i < 40; ++i) pool.add_job([&] {
          check(params().water_delta == .023 && params().quiet && params().workers == 2, "worker config snapshot");
          ++done;
        });
        pool.wait_all();
      }
      pool.add_job([] { throw std::runtime_error("expected worker failure"); });
      pool.add_job([&] { ++done; });
      bool caught = false;
      try { pool.wait_all(); } catch (const std::runtime_error&) { caught = true; }
      check(caught && done == 801, "worker exception propagated after drain");
      pool.add_job([&] { ++done; }); pool.wait_all();
      check(done == 802, "pool recovers after worker failure");
    }
    {
      ThreadPool pool;
      for (unsigned i = 0; i < 50; ++i) pool.add_job([&] { ++done; });
      // Destructor drains safely without explicit wait_all, including unwinding.
    }
    check(done == 852, "destructor drains jobs");
    std::cout << "Thread-pool regressions passed\n";
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
