import uuid
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

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


@pytest.mark.postgres
def test_concurrent_identical_requests_only_debit_once(
    postgres_engine,
    postgres_client: TestClient,
    postgres_auth_headers: dict[str, str],
    postgres_funded_accounts: dict[str, str],
):
    """Race: N threads POST the same payment with the same Idempotency-Key at once.

    Expect exactly one payment row and one debit. Requires PostgreSQL row locking.
    Run: docker compose exec api pytest -v -k concurrent_identical
    """
    key = str(uuid.uuid4())
    headers = make_payment_headers(postgres_auth_headers, key)
    payload = _payment_payload(postgres_funded_accounts, "80.00")
    worker_count = 8

    session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=postgres_engine
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    def send_payment() -> tuple[int, str | None]:
        app.dependency_overrides[get_db] = override_get_db
        with TestClient(app) as thread_client:
            response = thread_client.post("/payments", json=payload, headers=headers)
            payment_id = response.json().get("id") if response.status_code == 201 else None
            return response.status_code, payment_id

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(send_payment) for _ in range(worker_count)]
        results = [future.result() for future in as_completed(futures)]

    statuses = [status for status, _ in results]
    payment_ids = {pid for _, pid in results if pid is not None}

    assert all(status == 201 for status in statuses), f"Unexpected statuses: {statuses}"
    assert len(payment_ids) == 1, f"Expected one payment id, got: {payment_ids}"

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as verify_client:
        sender_balance = Decimal(
            verify_client.get(
                f"/accounts/{postgres_funded_accounts['sender_id']}",
                headers=postgres_auth_headers,
            ).json()["balance"]
        )
        payments = verify_client.get("/payments", headers=postgres_auth_headers).json()

    assert sender_balance == Decimal("920.00")
    matching = [p for p in payments if Decimal(p["amount"]) == Decimal("80.00")]
    assert len(matching) == 1
    assert matching[0]["id"] == payment_ids.pop()
