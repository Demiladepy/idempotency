# Idempotent Payments API

Production-style REST API implementing Stripe-style idempotency keys to safely handle duplicate payment requests under network failures.

**Status:** Week 5 — idempotency layer (Stripe-style idempotency keys)

## Stack

- FastAPI + Uvicorn
- PostgreSQL + SQLAlchemy 2.0
- Alembic (migrations)
- Docker + docker-compose

## Planned endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Create user account ✅ |
| POST | `/auth/login` | Get JWT token ✅ |
| GET | `/accounts/{id}` | Get account balance ✅ |
| POST | `/accounts` | Create account for authenticated user ✅ |
| POST | `/payments` | Create payment (idempotent) ✅ |
| GET | `/payments/{id}` | Get payment details ✅ |
| GET | `/payments` | List user's payments ✅ |

## Quick start

### Prerequisites

- Docker Desktop
- Python 3.12+ (optional, for local dev outside Docker)

### Run with Docker

```bash
docker compose up --build
```

- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Health: http://localhost:8000/health

### Run migrations

```bash
docker compose exec api alembic upgrade head
```

### Auth (Week 2)

```bash
# Register
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secretpass123"}'

# Login — returns JWT
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secretpass123"}'
```

### Accounts (Week 3)

```bash
# Create account (requires JWT from login)
curl -X POST http://localhost:8000/accounts \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"currency":"USD"}'

# Get account balance
curl http://localhost:8000/accounts/ACCOUNT_UUID \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Payments (Week 4–5)

```bash
# Transfer — Idempotency-Key required (generate a UUID per intent)
curl -X POST http://localhost:8000/payments \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Idempotency-Key: a3f1b2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c" \
  -H "Content-Type: application/json" \
  -d '{"from_account":"ACC-SENDER001","to_account":"ACC-RECEIVER01","amount":100.00,"currency":"USD"}'

# Retry with same key + same body → cached response, no double charge
curl -X POST http://localhost:8000/payments \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Idempotency-Key: a3f1b2c4-5d6e-7f8a-9b0c-1d2e3f4a5b6c" \
  -H "Content-Type: application/json" \
  -d '{"from_account":"ACC-SENDER001","to_account":"ACC-RECEIVER01","amount":100.00,"currency":"USD"}'

curl http://localhost:8000/payments \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Tests

```bash
pip install -r requirements.txt
pytest -v
```

### Local development (without Docker)

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env
# Start Postgres separately, then:
uvicorn app.main:app --reload
```

## Project roadmap

| Week | Goal |
|------|------|
| 1 | Repo, FastAPI, Postgres, Docker, models, migrations |
| 2 | User registration + JWT auth ✅ |
| 3 | Account creation + balance retrieval ✅ |
| 4 | Basic payment endpoint (no idempotency) ✅ |
| 5 | Idempotency layer (SERIALIZABLE + row locking) ✅ |
| 6 | Tests, deployment, README, interview prep |

## Known limitations

If the server crashes after processing a payment but before writing the idempotency record, a client retry could process the payment twice. Real systems address this with durable execution / write-ahead logs. This gap is documented intentionally — see interview prep notes in Week 6.

## References

- [Stripe idempotency docs](https://stripe.com/docs/api/idempotent_requests)
- [Implementing Stripe-like Idempotency Keys in Postgres](https://brandur.org/idempotency-keys) — Brandur Leach
