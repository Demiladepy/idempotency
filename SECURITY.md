# Security Audit

Audit date: 2026-06-07  
Scope: Idempotent Payments API (local/demo deployment)  
Verdict: **Suitable for portfolio, demos, and interview walkthroughs. Not ready for real-money production without additional controls.**

---

## Summary

| Category | Rating | Notes |
|----------|--------|-------|
| Authentication | Good | bcrypt + JWT, algorithm pinned |
| Authorization | Good | Ownership checks on accounts/payments/keys |
| Input validation | Good | Pydantic on all request bodies |
| Data integrity | Good | Transactions, row locks, DECIMAL for money |
| Idempotency | Good | Hash collision detection, user scoping |
| Secrets management | Acceptable (dev) | Env vars; weak defaults blocked in production |
| Transport security | Gap | HTTPS not configured (deployment concern) |
| Abuse resistance | Gap | No rate limiting |
| Observability | Gap | No structured audit logging |

---

## Checklist

### Authentication & sessions

- [x] Passwords hashed with bcrypt before storage
- [x] Password hash never returned in API responses
- [x] JWT `exp` claim set; algorithm restricted on decode
- [x] Login returns generic error for wrong email/password
- [x] Protected routes require valid Bearer token
- [ ] Refresh tokens / token revocation (not implemented — acceptable for scope)
- [ ] Multi-factor authentication (not implemented)

### Authorization

- [x] `GET /accounts/{id}` — owner only (403 for other users)
- [x] `POST /payments` — source account must belong to caller
- [x] `GET /payments/{id}` — sender or receiver only
- [x] Idempotency key validated against authenticated user
- [x] Destination account can belong to another user (intentional transfer model)

### Input & injection

- [x] All DB queries via SQLAlchemy ORM (no string-concatenated SQL)
- [x] Email validated as `EmailStr`
- [x] Password min 8 / max 128 chars on register; max 128 on login
- [x] Currency restricted to 3 uppercase letters
- [x] Payment amount must be > 0
- [x] UUID path params validated by FastAPI

### Idempotency & financial logic

- [x] Idempotency-Key required on `POST /payments`
- [x] Request body SHA-256 hash stored for collision detection
- [x] Same key + different body → 422
- [x] Account balances updated inside locked transaction
- [x] Insufficient funds rejected before debit
- [x] Same-account transfer rejected
- [x] Currency mismatch rejected
- [ ] Serializable isolation explicitly set (uses READ COMMITTED + row locks — sufficient for this design)

### Infrastructure & configuration

- [x] `.env` gitignored; `.env.example` has placeholders only
- [x] OpenAPI docs disabled when `APP_ENV=production`
- [x] App refuses startup with weak `JWT_SECRET` in production
- [x] Production Docker image does not use `--reload`
- [ ] Postgres port should not be exposed in production deploy
- [ ] Dev credentials in `docker-compose.yml` — dev only, rotate for any shared environment

### Dependencies

Review `requirements.txt` periodically with `pip audit` or GitHub Dependabot. Pin versions are in place.

---

## Findings

### Fixed in this audit

1. **OpenAPI exposed in production** — docs/redoc/openapi now disabled when `APP_ENV=production`.
2. **Weak JWT secret allowed at startup** — production mode now requires ≥32 char non-default secret.
3. **Dockerfile used `--reload`** — removed from image; dev reload only via compose override.
4. **Unbounded login password length** — capped at 128 chars to limit bcrypt DoS payload size.

### Accepted for project scope (document in interviews)

1. **No rate limiting** — add at API gateway before any public deployment.
2. **Email enumeration on register (409)** — tradeoff for clear UX in demo API.
3. **External charge outside the database transaction** — the in-database charge and idempotency row commit together, and `scripts/crash_harness.py` checks a hard exit before that commit. A card acquirer that captures before this commit would still need an outbox.
4. **JWT revocation** — 60-minute expiry only; no blocklist.

### Before real deployment (Week 6 / Railway)

- [x] Deployed on Render: https://idempotency-9sp0.onrender.com
- [ ] Set strong `JWT_SECRET` via platform secrets
- [ ] Set `APP_ENV=production`
- [ ] Link Render Postgres `DATABASE_URL` (Internal URL)
- [ ] Verify `/health` returns database connected
- [ ] Enable HTTPS (Render provides this automatically)
- [ ] Add rate limiting (e.g. slowapi or edge proxy)

---

## Test evidence

Run the security-relevant test suite:

```bash
pytest -v tests/test_auth.py tests/test_accounts.py tests/test_payments.py tests/test_idempotency.py
```

Key scenarios covered:
- Unauthorized access returns 403
- Cross-user account access returns 403
- Idempotent retry does not double-debit
- Idempotency key collision returns 422
- Concurrent identical requests (8 threads, same `Idempotency-Key`) create one payment only (`pytest -m postgres`)

---

## Reporting vulnerabilities

This is a personal portfolio project. If you discover a security issue, open a private issue or contact the repository owner directly.
