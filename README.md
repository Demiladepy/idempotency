# Idempotent Payments API

Production-style REST API implementing Stripe-style idempotency keys to safely handle duplicate payment requests under network failures.

**Status:** Week 3 — account creation + balance retrieval

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
| POST | `/payments` | Create payment (idempotent) |
| GET | `/payments/{id}` | Get payment details |
| GET | `/payments` | List user's payments |

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
| 4 | Basic payment endpoint (no idempotency) |
| 5 | Idempotency layer (SERIALIZABLE + row locking) |
| 6 | Tests, deployment, README, interview prep |

## Known limitations (to document fully in Week 6)

If the server crashes after processing a payment but before writing the idempotency record, a client retry could process the payment twice. Real systems address this with durable execution / write-ahead logs.

## References

- [Stripe idempotency docs](https://stripe.com/docs/api/idempotent_requests)
- [Implementing Stripe-like Idempotency Keys in Postgres](https://brandur.org/idempotency-keys) — Brandur Leach
