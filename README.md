# Idempotent Payments API

Production-style REST API that implements **Stripe-style idempotency keys** so duplicate payment requests (network retries, double-clicks) never double-charge a customer.

Built as a portfolio project for banking/tech interviews — demonstrates distributed systems thinking, ACID transactions, API design, and honest failure-mode analysis.

**Live:** https://idempotency-9sp0.onrender.com

---

## What it does

| Problem | Solution |
|---------|----------|
| Client retries the same payment | `Idempotency-Key` header caches the first response |
| Same key, different payload | **422** — client bug detected via SHA-256 request hash |
| Concurrent duplicate requests | Row-level locks on idempotency record + accounts |
| Unauthorized access | JWT auth + ownership checks on accounts and payments |

---

## Stack

| Layer | Technology |
|-------|------------|
| API | FastAPI, Pydantic, Uvicorn |
| Database | PostgreSQL 16, SQLAlchemy 2.0, Alembic |
| Auth | bcrypt, JWT (HS256) |
| Infra | Docker, docker-compose, [Render](https://render.com) |
| Tests | pytest, httpx |

---

## API reference

All endpoints except `/`, `/health`, and `/auth/*` require `Authorization: Bearer <JWT>`.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Service status |
| `GET` | `/health` | DB connectivity check |
| `POST` | `/auth/register` | Create user (email + password) |
| `POST` | `/auth/login` | Returns JWT access token |
| `POST` | `/accounts` | Create account for authenticated user |
| `GET` | `/accounts/{id}` | Get account balance (owner only) |
| `POST` | `/payments` | Transfer funds (**requires `Idempotency-Key`**) |
| `GET` | `/payments/{id}` | Payment details (sender or receiver) |
| `GET` | `/payments` | List user's payments |

Interactive docs (development only): http://localhost:8000/docs

Production: https://idempotency-9sp0.onrender.com (docs disabled when `APP_ENV=production`)

---

## Deploy on Render

**Live URL:** https://idempotency-9sp0.onrender.com

| Setting | Value |
|---------|--------|
| Environment | Docker |
| Root Directory | *(blank if repo root is this project)* |
| Dockerfile | `Dockerfile` |

**Required environment variables:**

| Variable | Value |
|----------|--------|
| `DATABASE_URL` | Render Postgres **Internal Database URL** |
| `APP_ENV` | `production` |
| `JWT_SECRET` | Random string, 32+ characters |
| `JWT_ALGORITHM` | `HS256` |
| `JWT_EXPIRE_MINUTES` | `60` |

On startup, the container runs `alembic upgrade head` then starts Uvicorn on Render's `$PORT`.

**Post-deploy checklist:**
1. Create a Render **PostgreSQL** database (if not already)
2. Link `DATABASE_URL` on the web service (Internal URL, not External)
3. Redeploy — migrations run automatically on boot
4. Verify: `GET /health` → `{"status":"ok","database":"connected"}`

---

## Quick start

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

### Run

```bash
git clone <your-repo-url>
cd idempotent-payments-api

docker compose up --build
docker compose exec api alembic upgrade head
```

- API: http://localhost:8000  
- Health: http://localhost:8000/health  

### End-to-end flow

```bash
# 1. Register
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secretpass123"}'

# 2. Login — save the token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secretpass123"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 3. Create two accounts
ACC1=$(curl -s -X POST http://localhost:8000/accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"currency":"USD"}')

# Fund sender for demo (production would use a deposit endpoint)
# Use account id/balance from ACC1 response as needed

ACC2=$(curl -s -X POST http://localhost:8000/accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"currency":"USD"}')

# 4. Pay — generate ONE idempotency key per payment intent
IDEM_KEY=$(python -c "import uuid; print(uuid.uuid4())")

curl -s -X POST http://localhost:8000/payments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $IDEM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"from_account":"ACC-...","to_account":"ACC-...","amount":100.00,"currency":"USD"}'

# 5. Retry with same key + same body → same payment, no second debit
curl -s -X POST http://localhost:8000/payments \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $IDEM_KEY" \
  -H "Content-Type: application/json" \
  -d '{"from_account":"ACC-...","to_account":"ACC-...","amount":100.00,"currency":"USD"}'
```

### Tests

```bash
pip install -r requirements.txt
pytest -v

# Inside Docker (uses Postgres)
docker compose exec api pytest -v

# Race condition test only (requires PostgreSQL)
docker compose exec api pytest -v -m postgres -k concurrent_identical

# Crash before the shared commit, then retry. Expect 1 payment, 20/20.
python scripts/crash_harness.py --runs 20

# 200 concurrent requests, one Idempotency-Key, 50 times. Expect 1 payment each time.
python scripts/concurrency_idempotency.py --requests 200 --loops 50
```

### Failure injection

`POST /payments` inserts an idempotency placeholder, applies the charge, then commits both in one transaction. `CRASH_AFTER=charge_committed` calls `os._exit(1)` after the charge flush and before that commit. The process dies without a cleanup commit, Postgres aborts the open transaction, and the retry finds no row.

`scripts/crash_harness.py` starts the API with that variable, sends one payment, waits for the process to exit 1, restarts without the variable, resends the same key, and counts `payments` for the sender. Locally that was **20/20 with exactly one payment**. A count of 2 would mean the charge had committed on its own.

`scripts/concurrency_idempotency.py` is the load-side check: N in-flight requests, one key, `SELECT COUNT(*)` equals 1. Waiters block on `SELECT ... FOR UPDATE` until the winner commits. Locally, 200 requests with one key all returned 201 and created one payment. See [BENCHMARKS.md](BENCHMARKS.md).

The limit of this fix: it holds only while the charge is a row in this database. A capture on an external acquirer commits outside the transaction, and a crash after that capture still double-charges. That case needs an outbox, which this service does not implement.

**Current coverage:** 32 tests — auth, accounts, payments, idempotency retry/collision, crash-hook placement, and concurrent duplicate-request safety (Postgres).

### Local dev (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
copy .env.example .env            # set DATABASE_URL, JWT_SECRET
uvicorn app.main:app --reload
```

---

## How idempotency works

```
POST /payments
Header: Idempotency-Key: <uuid>
Body:   { from_account, to_account, amount, currency }

Server (single DB transaction):
  1. Lock idempotency record (SELECT ... FOR UPDATE)
  2. If key exists:
       same request hash → return cached response
       different hash    → 422 conflict
  3. If key is new:
       insert placeholder → lock accounts → debit/credit → store response
  4. Commit
```

**Design choices:**
- Request body hashed with SHA-256 (canonical JSON) to detect key reuse bugs
- Account rows locked in sorted ID order to prevent deadlocks
- Idempotency records expire after **24 hours** (Stripe-style)
- Keys are scoped to the authenticated user

---

## Security

This project applies production-*style* security patterns appropriate for a portfolio/demo API. It is **not** production-hardened for real money.

### What is implemented

| Control | Status |
|---------|--------|
| Password hashing (bcrypt, never stored plaintext) | ✅ |
| JWT with expiry; algorithm pinned on decode | ✅ |
| Generic login errors (no password leak) | ✅ |
| Authorization on accounts, payments, idempotency keys | ✅ |
| SQL injection protection (SQLAlchemy ORM, no raw user SQL) | ✅ |
| Input validation (Pydantic: email, password length, currency format) | ✅ |
| OpenAPI docs disabled when `APP_ENV=production` | ✅ |
| Startup refuses weak `JWT_SECRET` in production | ✅ |
| Docker image runs without `--reload` (dev reload via compose only) | ✅ |

### Known gaps (document honestly in interviews)

| Gap | Risk | Production mitigation |
|-----|------|---------------------|
| No rate limiting on `/auth/login` or `/auth/register` | Brute-force / abuse | API gateway, WAF, rate limiter (Redis) |
| Register returns **409** for duplicate email | Email enumeration | Generic response or CAPTCHA |
| No HTTPS in local Docker setup | Token interception | TLS termination at load balancer |
| JWT cannot be revoked before expiry | Stolen token usable until expiry | Short TTL + refresh tokens + blocklist |
| Crash between charge flush and commit | No double-pay: both rows roll back. Harness: `scripts/crash_harness.py` | An external acquirer call would still sit outside this transaction; that needs an outbox |
| Postgres port exposed on localhost in compose | Dev-only exposure | Remove port mapping in production |
| Hardcoded dev DB credentials in compose | Dev-only | Secrets manager in production |

See [SECURITY.md](SECURITY.md) for the full audit checklist.

---

## Environment variables

Copy `.env.example` to `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | local docker URL |
| `APP_ENV` | `development` or `production` | `development` |
| `JWT_SECRET` | HS256 signing key (≥32 chars in production) | dev placeholder |
| `JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `JWT_EXPIRE_MINUTES` | Token lifetime | `60` |
| `CRASH_AFTER` | Hard-exit point for the failure harness. Unset in normal runs | unset |

---

## Project structure

```
app/
├── main.py              # FastAPI app, health check
├── crash.py             # CRASH_AFTER hard-exit hook
├── config.py            # Settings from environment
├── database.py          # SQLAlchemy session
├── models.py            # User, Account, Payment, IdempotencyRecord
├── auth/                # JWT + get_current_user dependency
├── routers/             # auth, accounts, payments
├── schemas/             # Pydantic request/response models
└── services/            # Payment + idempotency business logic
scripts/                 # Crash harness and concurrency check
alembic/                 # Database migrations
tests/                   # pytest suite
```

---

## Interview narrative (60 seconds)

> "I built an idempotent payments API because duplicate execution is one of the hardest real problems in payment systems — not CRUD, but correctness under failure.
>
> Clients send an Idempotency-Key with every payment. The server hashes the request body, uses Postgres row locks to handle concurrent duplicates, and returns the cached response on retry instead of charging twice.
>
> I can walk through the three scenarios — new key, same key same body, same key different body. The charge and the idempotency row commit together, and a crash harness hard-exits before that commit, restarts, and checks the retry still created one payment. The limit is an external charge that commits outside Postgres: that needs an outbox."

---

## References

- [Stripe — Idempotent requests](https://stripe.com/docs/api/idempotent_requests)
- [Implementing Stripe-like Idempotency Keys in Postgres](https://brandur.org/idempotency-keys) — Brandur Leach

---

## License

MIT (add your license file if open-sourcing)
