# Idempotent Payments API

Production-style REST API that implements **Stripe-style idempotency keys** so duplicate payment requests (network retries, double-clicks) never double-charge a customer.

Built as a portfolio project for banking/tech interviews — demonstrates distributed systems thinking, ACID transactions, API design, and honest failure-mode analysis.

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
| Infra | Docker, docker-compose |
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
```

**Current coverage:** 27 tests passing (auth, accounts, payments, idempotency retry + collision detection).

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
| Crash after payment, before idempotency write | Possible double-pay on retry | Durable execution / outbox pattern |
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

---

## Project structure

```
app/
├── main.py              # FastAPI app, health check
├── config.py            # Settings from environment
├── database.py          # SQLAlchemy session
├── models.py            # User, Account, Payment, IdempotencyRecord
├── auth/                # JWT + get_current_user dependency
├── routers/             # auth, accounts, payments
├── schemas/             # Pydantic request/response models
└── services/            # Payment + idempotency business logic
alembic/                 # Database migrations
tests/                   # pytest suite
```

---

## Interview narrative (60 seconds)

> "I built an idempotent payments API because duplicate execution is one of the hardest real problems in payment systems — not CRUD, but correctness under failure.
>
> Clients send an Idempotency-Key with every payment. The server hashes the request body, uses Postgres row locks to handle concurrent duplicates, and returns the cached response on retry instead of charging twice.
>
> I can walk through the three scenarios — new key, same key same body, same key different body — and I'm honest about what I didn't solve: if the server crashes between executing the payment and persisting the idempotency record, a retry could still double-pay. Production systems use durable execution logs for that."

---

## References

- [Stripe — Idempotent requests](https://stripe.com/docs/api/idempotent_requests)
- [Implementing Stripe-like Idempotency Keys in Postgres](https://brandur.org/idempotency-keys) — Brandur Leach

---

## License

MIT (add your license file if open-sourcing)
