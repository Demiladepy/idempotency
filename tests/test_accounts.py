from decimal import Decimal

from fastapi.testclient import TestClient


def test_create_account_success(client, auth_headers):
    response = client.post(
        "/accounts",
        json={"currency": "USD"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["currency"] == "USD"
    assert data["balance"] == "0.00"
    assert data["account_number"].startswith("ACC-")
    assert len(data["account_number"]) == 16  # ACC- + 12 hex chars


def test_create_account_requires_auth(client):
    response = client.post("/accounts", json={"currency": "USD"})
    assert response.status_code == 403


def test_create_account_invalid_currency(client, auth_headers):
    response = client.post(
        "/accounts",
        json={"currency": "usd"},
        headers=auth_headers,
    )
    assert response.status_code == 422


def test_get_account_success(client, auth_headers):
    create_response = client.post(
        "/accounts",
        json={"currency": "EUR"},
        headers=auth_headers,
    )
    account_id = create_response.json()["id"]

    response = client.get(f"/accounts/{account_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == account_id
    assert data["currency"] == "EUR"
    assert Decimal(data["balance"]) == Decimal("0.00")


def test_get_account_not_found(client, auth_headers):
    response = client.get(
        "/accounts/00000000-0000-0000-0000-000000000001",
        headers=auth_headers,
    )
    assert response.status_code == 404


def test_get_account_forbidden_other_user(
    client: TestClient,
    auth_headers: dict[str, str],
    other_user_headers: dict[str, str],
):
    create_response = client.post(
        "/accounts",
        json={"currency": "USD"},
        headers=auth_headers,
    )
    account_id = create_response.json()["id"]

    response = client.get(f"/accounts/{account_id}", headers=other_user_headers)
    assert response.status_code == 403
    assert response.json()["detail"] == "Not authorized to access this account"


def test_get_account_requires_auth(client, auth_headers):
    create_response = client.post(
        "/accounts",
        json={"currency": "GBP"},
        headers=auth_headers,
    )
    account_id = create_response.json()["id"]

    response = client.get(f"/accounts/{account_id}")
    assert response.status_code == 403
