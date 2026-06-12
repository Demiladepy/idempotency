from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.accounts import router as accounts_router
from app.routers.auth import router as auth_router

app = FastAPI(
    title="Idempotent Payments API",
    description="REST API for safe payment processing with Stripe-style idempotency keys.",
    version="0.1.0",
)

app.include_router(auth_router)
app.include_router(accounts_router)


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
