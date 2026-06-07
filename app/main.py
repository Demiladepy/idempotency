from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.database import check_db_connection, get_db

app = FastAPI(
    title="Idempotent Payments API",
    description="REST API for safe payment processing with Stripe-style idempotency keys.",
    version="0.1.0",
)


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        check_db_connection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok", "database": "connected"}
