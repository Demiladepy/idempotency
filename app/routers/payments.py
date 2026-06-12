import uuid

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import User
from app.schemas.payment import CreatePaymentRequest, PaymentResponse
from app.services import payments as payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post(
    "",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_payment(
    payload: CreatePaymentRequest,
    response: Response,
    idempotency_key: uuid.UUID = Header(..., alias="Idempotency-Key"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    request_hash = payment_service.hash_payment_request(
        from_account=payload.from_account,
        to_account=payload.to_account,
        amount=payload.amount,
        currency=payload.currency,
    )
    body, status_code = payment_service.create_payment_idempotent(
        db=db,
        user=current_user,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        from_account_number=payload.from_account,
        to_account_number=payload.to_account,
        amount=payload.amount,
        currency=payload.currency,
    )
    response.status_code = status_code
    return body


@router.get("", response_model=list[PaymentResponse])
def list_payments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return payment_service.list_user_payments(db, current_user)


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(
    payment_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return payment_service.get_user_payment(db, current_user, payment_id)
