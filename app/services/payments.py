from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Payment, User


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


def create_payment(
    db: Session,
    user: User,
    from_account_number: str,
    to_account_number: str,
    amount: Decimal,
    currency: str,
) -> dict:
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
    db.commit()
    db.refresh(payment)

    return _payment_response(payment, from_account, to_account)


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
