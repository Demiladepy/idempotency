from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, User


def test_create_payment_success(client, auth_headers, funded_accounts):
    response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "250.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["from_account"] == funded_accounts["sender"]
    assert data["to_account"] == funded_accounts["receiver"]
    assert data["amount"] == "250.00"
    assert data["currency"] == "USD"
    assert data["status"] == "completed"

    sender_balance = client.get(
        f"/accounts/{funded_accounts['sender_id']}",
        headers=auth_headers,
    ).json()["balance"]
    assert Decimal(sender_balance) == Decimal("750.00")


def test_create_payment_insufficient_funds(client, auth_headers, funded_accounts):
    response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "5000.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Insufficient funds"


def test_create_payment_same_account(client, auth_headers, funded_accounts):
    response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["sender"],
            "amount": "10.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_create_payment_source_not_found(client, auth_headers, funded_accounts):
    response = client.post(
        "/payments",
        json={
            "from_account": "ACC-DOESNOTEXIST",
            "to_account": funded_accounts["receiver"],
            "amount": "10.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_create_payment_forbidden_source(
    client: TestClient,
    db_session: Session,
    auth_headers: dict[str, str],
    other_user_headers: dict[str, str],
    funded_accounts: dict[str, str],
):
    import uuid
    from decimal import Decimal

    other_user = db_session.execute(
        select(User).where(User.email == "other@example.com")
    ).scalar_one()
    foreign_account = Account(
        user_id=other_user.id,
        account_number="ACC-FOREIGN001",
        balance=Decimal("500.00"),
        currency="USD",
    )
    db_session.add(foreign_account)
    db_session.commit()

    response = client.post(
        "/payments",
        json={
            "from_account": "ACC-FOREIGN001",
            "to_account": funded_accounts["receiver"],
            "amount": "10.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    assert response.status_code == 403


def test_create_payment_requires_auth(client, funded_accounts):
    response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "10.00",
            "currency": "USD",
        },
    )
    assert response.status_code == 403


def test_get_payment_success(client, auth_headers, funded_accounts):
    create_response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "50.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    payment_id = create_response.json()["id"]

    response = client.get(f"/payments/{payment_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == payment_id


def test_get_payment_forbidden(
    client: TestClient,
    db_session: Session,
    auth_headers: dict[str, str],
    other_user_headers: dict[str, str],
    funded_accounts: dict[str, str],
):
    create_response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "25.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    payment_id = create_response.json()["id"]

    response = client.get(f"/payments/{payment_id}", headers=other_user_headers)
    assert response.status_code == 403


def test_list_payments(client, auth_headers, funded_accounts):
    client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "10.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )
    client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "20.00",
            "currency": "USD",
        },
        headers=auth_headers,
    )

    response = client.get("/payments", headers=auth_headers)
    assert response.status_code == 200
    payments = response.json()
    assert len(payments) == 2
    amounts = {Decimal(p["amount"]) for p in payments}
    assert amounts == {Decimal("10.00"), Decimal("20.00")}
