import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from tests.conftest import make_payment_headers


def _payment_payload(funded_accounts: dict[str, str], amount: str = "100.00") -> dict:
    return {
        "from_account": funded_accounts["sender"],
        "to_account": funded_accounts["receiver"],
        "amount": amount,
        "currency": "USD",
    }


def test_idempotent_retry_returns_same_payment(client, auth_headers, funded_accounts):
    key = str(uuid.uuid4())
    headers = make_payment_headers(auth_headers, key)
    payload = _payment_payload(funded_accounts, "100.00")

    first = client.post("/payments", json=payload, headers=headers)
    second = client.post("/payments", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    sender_balance = client.get(
        f"/accounts/{funded_accounts['sender_id']}",
        headers=auth_headers,
    ).json()["balance"]
    assert Decimal(sender_balance) == Decimal("900.00")


def test_idempotency_key_reused_with_different_body(client, auth_headers, funded_accounts):
    key = str(uuid.uuid4())
    headers = make_payment_headers(auth_headers, key)

    first = client.post(
        "/payments",
        json=_payment_payload(funded_accounts, "50.00"),
        headers=headers,
    )
    assert first.status_code == 201

    second = client.post(
        "/payments",
        json=_payment_payload(funded_accounts, "75.00"),
        headers=headers,
    )
    assert second.status_code == 422
    assert second.json()["detail"] == "Idempotency key reused with different request body"

    sender_balance = client.get(
        f"/accounts/{funded_accounts['sender_id']}",
        headers=auth_headers,
    ).json()["balance"]
    assert Decimal(sender_balance) == Decimal("950.00")


@pytest.mark.skip(reason="Concurrent idempotency is validated against Postgres in Docker")
def test_concurrent_identical_requests_only_debit_once(
    auth_headers: dict[str, str],
    funded_accounts: dict[str, str],
    db_engine,
):
    from collections.abc import Generator

    from sqlalchemy.orm import sessionmaker

    key = str(uuid.uuid4())
    headers = make_payment_headers(auth_headers, key)
    payload = _payment_payload(funded_accounts, "80.00")
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db() -> Generator:
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    def send_payment() -> int:
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as thread_client:
            response = thread_client.post("/payments", json=payload, headers=headers)
            return response.status_code

    with ThreadPoolExecutor(max_workers=4) as executor:
        statuses = list(executor.map(lambda _: send_payment(), range(4)))

    assert all(status == 201 for status in statuses)

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as verify_client:
        sender_balance = verify_client.get(
            f"/accounts/{funded_accounts['sender_id']}",
            headers=auth_headers,
        ).json()["balance"]
        payments = verify_client.get("/payments", headers=auth_headers).json()

    assert Decimal(sender_balance) == Decimal("920.00")
    matching = [p for p in payments if Decimal(p["amount"]) == Decimal("80.00")]
    assert len(matching) == 1
