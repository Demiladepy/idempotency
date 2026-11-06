"""Reproduce a crash between the charge flush and the shared commit.

The payment and the idempotency placeholder are one Postgres transaction.
CRASH_AFTER=charge_committed hard-exits after the charge is flushed and before
commit. The process dies, Postgres aborts the transaction, and a clean retry
of the same Idempotency-Key creates exactly one payment row.

A count of 2 would mean the charge committed before the crash. This service
does not do that. Each run asserts the count is 1.

Usage (Postgres must already be running):

    python scripts/crash_harness.py --runs 20
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_lib import (  # noqa: E402
    REPO_ROOT,
    count_payments,
    ensure_schema,
    log_tail,
    prepare_sender,
    release_open_transactions,
    start_server,
    stop_server,
    wait_healthy,
    wait_port_free,
)


def _post_payment(base_url: str, identity: dict[str, str], key: str, amount: str) -> httpx.Response:
    return httpx.post(
        f"{base_url}/payments",
        json={
            "from_account": identity["sender"],
            "to_account": identity["receiver"],
            "amount": amount,
            "currency": "USD",
        },
        headers={
            "Authorization": f"Bearer {identity['token']}",
            "Idempotency-Key": key,
        },
        timeout=30.0,
    )


def run_once(port: int, run_index: int) -> int:
    base_url = f"http://127.0.0.1:{port}"
    wait_port_free(port)
    log_path = REPO_ROOT / f"harness-crash-{run_index}.log"
    proc, log_file = start_server(
        port,
        extra_env={"CRASH_AFTER": "charge_committed"},
        log_path=log_path,
    )
    identity: dict[str, str] | None = None
    key = str(uuid.uuid4())
    amount = "10.00"
    try:
        wait_healthy(base_url, proc, log_path)
        try:
            identity = prepare_sender(base_url)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"setup request failed: {exc}\n{log_tail(log_path)}") from exc
        try:
            response = _post_payment(base_url, identity, key, amount)
        except httpx.HTTPError:
            response = None
        else:
            if response.status_code < 500:
                raise RuntimeError(
                    "crash hook did not fire: "
                    f"HTTP {response.status_code} {response.text[:300]}\n"
                    f"{log_tail(log_path)}"
                )

        try:
            code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"server stayed up after the crashing request\n{log_tail(log_path)}"
            ) from None
        if code != 1:
            raise RuntimeError(f"expected os._exit(1), got {code}\n{log_tail(log_path)}")
    finally:
        if proc.poll() is None:
            stop_server(proc)
        log_file.close()

    if identity is None:
        raise RuntimeError("setup failed before the crash request")

    release_open_transactions()
    wait_port_free(port)
    clean_log = REPO_ROOT / f"harness-clean-{run_index}.log"
    clean, clean_file = start_server(port, log_path=clean_log)
    try:
        wait_healthy(base_url, clean, clean_log)
        retry = _post_payment(base_url, identity, key, amount)
        if retry.status_code != 201:
            raise RuntimeError(
                f"retry returned HTTP {retry.status_code}: {retry.text[:300]}\n"
                f"{log_tail(clean_log)}"
            )
        return count_payments(identity["sender"])
    finally:
        stop_server(clean)
        clean_file.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")

    print(
        "Ordering: charge flush and idempotency placeholder share one "
        "transaction. Crash before commit rolls both back. Retry must "
        "leave exactly 1 payment.",
        flush=True,
    )
    ensure_schema()
    failures: list[str] = []
    for index in range(1, args.runs + 1):
        # A fresh port per run. Rebinding the port we just killed flakes on Windows.
        count = run_once(args.port + index, index)
        status = "ok" if count == 1 else "FAIL"
        print(f"run {index}: payment_count={count} {status}", flush=True)
        if count != 1:
            failures.append(f"run {index} count={count}")

    if failures:
        raise SystemExit("double-charge or missing charge: " + "; ".join(failures))
    print(f"{args.runs}/{args.runs} retries left exactly one payment")


if __name__ == "__main__":
    main()
