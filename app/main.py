import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.routers.accounts import router as accounts_router
from app.routers.auth import router as auth_router
from app.routers.payments import router as payments_router

_INSECURE_JWT_SECRETS = frozenset(
    {
        "dev-secret-change-before-production",
        "change-me-in-production-use-a-long-random-string",
    }
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tokens = os.environ.get("THREAD_POOL_TOKENS", "").strip()
    if tokens:
        import anyio

        anyio.to_thread.current_default_thread_limiter().total_tokens = int(tokens)
    if settings.app_env == "production":
        if settings.jwt_secret in _INSECURE_JWT_SECRETS:
            raise RuntimeError(
                "JWT_SECRET must be set to a strong random value when APP_ENV=production"
            )
        if len(settings.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be at least 32 characters in production")
    yield


app = FastAPI(
    title="Idempotent Payments API",
    description="REST API for safe payment processing with Stripe-style idempotency keys.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url="/redoc" if settings.app_env != "production" else None,
    openapi_url="/openapi.json" if settings.app_env != "production" else None,
)

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(payments_router)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "connected"}
