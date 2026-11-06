# Benchmarks

Measured locally on 5 Nov 2026 against Postgres 16 from `docker compose` (`max_connections=300`) on Windows. These are the runs that completed. Latency percentiles were not collected.

## Crash before the shared commit

```bash
python scripts/crash_harness.py --runs 20
```

The harness sets `CRASH_AFTER=charge_committed`, sends one payment, waits for process exit code 1, restarts with the variable unset, and resends the same idempotency key.

| Runs | Payment rows after retry | Wall clock |
|------|--------------------------|------------|
| 20/20 | 1 | 4 min 23 s |

A count of 2 would mean the charge committed before the process died. The charge and the idempotency placeholder are one transaction, so the crash rolls both back.

## One key, 200 in-flight requests

```bash
python scripts/concurrency_idempotency.py --requests 200 --loops 1
```

| Loop | New payment rows | HTTP statuses |
|------|------------------|---------------|
| 1 | 1 | 201 × 200 |

That run raised the API pool for the harness process only: `DB_POOL_SIZE=40`, `DB_MAX_OVERFLOW=180`, `THREAD_POOL_TOKENS=220`.

An earlier 200-request run on the default pool (5 connections, overflow 10) also left **1** payment row. 120 requests failed in the client and 40 returned HTTP 500 with `QueuePool limit of size 5 overflow 10 reached`. The duplicate charge did not happen. The pool change is what made every request succeed, not what made the count 1.
