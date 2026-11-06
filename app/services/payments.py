import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.crash import AFTER_CHARGE_FLUSH, crash_after
from app.models import Account, IdempotencyRecord, Payment, User
from app.schemas.payment import PaymentResponse

IDEMPOTENCY_TTL_HOURS = 24
PROCESSING_STATUS = 0


def hash_payment_request(
    from_account: str,
    to_account: str,
    amount: Decimal,
    currency: str,
) -> str:
    payload = json.dumps(
        {
            "from_account": from_account,
            "to_account": to_account,
            "amount": str(amount),
            "currency": currency,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _payment_response(payment: Payment, from_account: Account, to_account: Account) -> dict:
    return {
        "id": payment.id,
        "from_account": from_account.account_number,
        "to_account": to_account.account_number,
        "amount": payment.amount,
        "currency": payment.currency,
        "status": payment.status,
        "created_at": payment.created_at,
    }


def _serialize_response(response: dict) -> dict:
    return PaymentResponse.model_validate(response).model_dump(mode="json")


def _execute_payment(
    db: Session,
    user: User,
    from_account_number: str,
    to_account_number: str,
    amount: Decimal,
    currency: str,
) -> tuple[Payment, Account, Account]:
    if from_account_number == to_account_number:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot transfer to the same account",
        )

    from_account = db.execute(
        select(Account).where(Account.account_number == from_account_number)
    ).scalar_one_or_none()
    if from_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source account not found",
        )
    if from_account.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to use this source account",
        )

    to_account = db.execute(
        select(Account).where(Account.account_number == to_account_number)
    ).scalar_one_or_none()
    if to_account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destination account not found",
        )

    if from_account.currency != currency or to_account.currency != currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Currency mismatch between accounts or request",
        )

    first_id, second_id = sorted([from_account.id, to_account.id])
    locked_accounts = db.execute(
        select(Account)
        .where(Account.id.in_([first_id, second_id]))
        .order_by(Account.id)
        .with_for_update()
    ).scalars().all()
    locked = {account.id: account for account in locked_accounts}
    from_account = locked[from_account.id]
    to_account = locked[to_account.id]

    if from_account.balance < amount:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient funds",
        )

    from_account.balance -= amount
    to_account.balance += amount

    payment = Payment(
        from_account_id=from_account.id,
        to_account_id=to_account.id,
        amount=amount,
        currency=currency,
        status="completed",
    )
    db.add(payment)
    db.flush()
    db.refresh(payment)

    return payment, from_account, to_account


def _validate_existing_record(
    existing: IdempotencyRecord,
    user: User,
    request_hash: str,
) -> dict | None:
    now = datetime.now(UTC)
    expires_at = existing.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at <= now:
        return None

    if existing.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency key belongs to another user",
        )
    if existing.request_hash != request_hash:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency key reused with different request body",
        )
    if existing.response_status == PROCESSING_STATUS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Payment with this idempotency key is still processing",
        )
    return existing.response_body


def create_payment_idempotent(
    db: Session,
    user: User,
    idempotency_key: uuid.UUID,
    request_hash: str,
    from_account_number: str,
    to_account_number: str,
    amount: Decimal,
    currency: str,
) -> tuple[dict, int]:
    for attempt in range(2):
        try:
            existing = db.execute(
                select(IdempotencyRecord)
                .where(IdempotencyRecord.key == idempotency_key)
                .with_for_update()
            ).scalar_one_or_none()

            if existing:
                cached = _validate_existing_record(existing, user, request_hash)
                if cached is not None:
                    db.commit()
                    return cached, existing.response_status
                db.delete(existing)
                db.flush()

            expires_at = datetime.now(UTC) + timedelta(hours=IDEMPOTENCY_TTL_HOURS)
            placeholder = IdempotencyRecord(
                key=idempotency_key,
                user_id=user.id,
                request_hash=request_hash,
                response_body={},
                response_status=PROCESSING_STATUS,
                payment_id=None,
                expires_at=expires_at,
            )
            db.add(placeholder)
            db.flush()

            payment, from_account, to_account = _execute_payment(
                db=db,
                user=user,
                from_account_number=from_account_number,
                to_account_number=to_account_number,
                amount=amount,
                currency=currency,
            )
            response_body = _payment_response(payment, from_account, to_account)

            # Same transaction as the placeholder above. A hard exit here rolls
            # the charge and the idempotency row back together.
            crash_after(AFTER_CHARGE_FLUSH)

            placeholder.response_body = _serialize_response(response_body)
            placeholder.response_status = status.HTTP_201_CREATED
            placeholder.payment_id = payment.id

            db.commit()
            return response_body, status.HTTP_201_CREATED

        except IntegrityError:
            db.rollback()
            existing = db.execute(
                select(IdempotencyRecord)
                .where(IdempotencyRecord.key == idempotency_key)
                .with_for_update()
            ).scalar_one_or_none()
            if existing is not None:
                cached = _validate_existing_record(existing, user, request_hash)
                if cached is not None:
                    db.commit()
                    return cached, existing.response_status
            if attempt == 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Could not process idempotent payment request",
                ) from None
            continue
        except HTTPException:
            db.rollback()
            raise

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Could not process idempotent payment request",
    )


def get_user_payment(db: Session, user: User, payment_id) -> dict:
    payment = db.execute(
        select(Payment).where(Payment.id == payment_id)
    ).scalar_one_or_none()
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment not found",
        )

    from_account = db.execute(
        select(Account).where(Account.id == payment.from_account_id)
    ).scalar_one()
    to_account = db.execute(
        select(Account).where(Account.id == payment.to_account_id)
    ).scalar_one()

    if from_account.user_id != user.id and to_account.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this payment",
        )

    return _payment_response(payment, from_account, to_account)


def list_user_payments(db: Session, user: User) -> list[dict]:
    user_account_ids = select(Account.id).where(Account.user_id == user.id)
    payments = db.execute(
        select(Payment)
        .where(
            (Payment.from_account_id.in_(user_account_ids))
            | (Payment.to_account_id.in_(user_account_ids))
        )
        .order_by(Payment.created_at.desc(), Payment.id.desc())
    ).scalars().all()

    results = []
    for payment in payments:
        from_account = db.execute(
            select(Account).where(Account.id == payment.from_account_id)
        ).scalar_one()
        to_account = db.execute(
            select(Account).where(Account.id == payment.to_account_id)
        ).scalar_one()
        results.append(_payment_response(payment, from_account, to_account))
    return results
