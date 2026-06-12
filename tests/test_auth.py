def test_register_success(client):
    response = client.post(
        "/auth/register",
        json={"email": "newuser@example.com", "password": "secretpass123"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert "id" in data
    assert "created_at" in data
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email(client):
    payload = {"email": "dup@example.com", "password": "secretpass123"}
    client.post("/auth/register", json=payload)
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 409
    assert response.json()["detail"] == "Email already registered"


def test_register_short_password(client):
    response = client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_login_success(client):
    client.post(
        "/auth/register",
        json={"email": "login@example.com", "password": "secretpass123"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "secretpass123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 0


def test_login_wrong_password(client):
    client.post(
        "/auth/register",
        json={"email": "login@example.com", "password": "secretpass123"},
    )
    response = client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_login_unknown_email(client):
    response = client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "secretpass123"},
    )
    assert response.status_code == 401
