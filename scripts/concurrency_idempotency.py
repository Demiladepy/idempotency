"""Fire N concurrent payments with one Idempotency-Key and count rows.

Same key, same body, against a real uvicorn process and Postgres. The
idempotency row is locked with SELECT FOR UPDATE, so waiters observe the
winner's committed record instead of inserting a second payment.

Asserts exactly one payment row per key. Status codes other than 201 are
reported; a 409 from a waiter that observed the in-flight placeholder is
still a pass when the row count is 1.

Usage (Postgres must already be running):

    python scripts/concurrency_idempotency.py --requests 200 --loops 50
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

from harness_lib import (  # noqa: E402
    REPO_ROOT,
    count_payments,
    ensure_schema,
    prepare_sender,
    start_server,
    stop_server,
    wait_healthy,
)


async def burst(
    base_url: str,
    identity: dict[str, str],
    key: str,
    amount: str,
    requests: int,
) -> list[int]:
    headers = {
        "Authorization": f"Bearer {identity['token']}",
        "Idempotency-Key": key,
    }
    payload = {
        "from_account": identity["sender"],
        "to_account": identity["receiver"],
        "amount": amount,
        "currency": "USD",
    }

    async def one(client: httpx.AsyncClient) -> int:
        try:
            response = await client.post("/payments", json=payload, headers=headers)
        except httpx.HTTPError:
            return 0
        return response.status_code

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        return list(await asyncio.gather(*[one(client) for _ in range(requests)]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--loops", type=int, default=1)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if args.requests < 1 or args.loops < 1:
        raise SystemExit("--requests and --loops must be at least 1")

    ensure_schema()
    base_url = f"http://127.0.0.1:{args.port}"
    log_path = REPO_ROOT / "harness-concurrency.log"
    # One DB session and one worker thread per in-flight request.
    # Postgres must allow at least this many connections. The compose file sets 300.
    slots = args.requests
    proc, log_file = start_server(
        args.port,
        extra_env={
            "DB_POOL_SIZE": str(min(40, slots)),
            "DB_MAX_OVERFLOW": str(max(slots - 40, 0)),
            "THREAD_POOL_TOKENS": str(slots + 20),
        },
        log_path=log_path,
    )
    failures: list[str] = []
    try:
        wait_healthy(base_url, proc, log_path)
        identity = prepare_sender(base_url)
        for index in range(1, args.loops + 1):
            before = count_payments(identity["sender"])
            key = str(uuid.uuid4())
            amount = f"{index}.00"
            codes = asyncio.run(
                burst(base_url, identity, key, amount, args.requests)
            )
            delta = count_payments(identity["sender"]) - before
            histogram = Counter(codes)
            status = "ok" if delta == 1 else "FAIL"
            print(f"loop {index}: payment_delta={delta} statuses={dict(histogram)} {status}")
            if delta != 1:
                failures.append(f"loop {index} delta={delta} statuses={dict(histogram)}")
    finally:
        stop_server(proc)
        log_file.close()

    if failures:
        raise SystemExit("concurrency check failed: " + "; ".join(failures))
    print(f"{args.loops}/{args.loops} loops created exactly one payment")


if __name__ == "__main__":
    main()
