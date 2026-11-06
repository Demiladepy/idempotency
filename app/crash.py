"""Failure-injection points for the idempotency request path.

CRASH_AFTER names a point. When the request reaches that point the process
hard-exits with os._exit(1). That skips exception handlers, so the open
Postgres transaction is not committed and is aborted when the connection drops.

The only point on the payment path is after_charge_flush. The charge row has
been flushed inside the same transaction as the idempotency placeholder, and
neither has been committed. charge_committed is accepted as an alias for that
point: this service does not commit the charge on its own.
"""

from __future__ import annotations

import os

AFTER_CHARGE_FLUSH = "after_charge_flush"

# The sprint name for "charge is durable, idempotency record is not". That
# separate commit does not exist; the alias hits the pre-commit flush instead.
_ALIASES = {
    "charge_committed": AFTER_CHARGE_FLUSH,
}


def crash_after(point: str) -> None:
    requested = os.environ.get("CRASH_AFTER", "").strip()
    if not requested:
        return
    if _ALIASES.get(requested, requested) == point:
        os._exit(1)
