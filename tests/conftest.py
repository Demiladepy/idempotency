from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.database import get_db
from app.main import app
from app.models import Account, Payment, User


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    User.__table__.create(engine)
    Account.__table__.create(engine)
    Payment.__table__.create(engine)
    yield engine
    Payment.__table__.drop(engine)
    Account.__table__.drop(engine)
    User.__table__.drop(engine)


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    session = sessionmaker(bind=db_engine)()
    yield session
    session.close()


@pytest.fixture
def client(db_engine) -> Generator[TestClient, None, None]:
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)

    def override_get_db() -> Generator[Session, None, None]:
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    client.post(
        "/auth/register",
        json={"email": "user@example.com", "password": "secretpass123"},
    )
    login_response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secretpass123"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_user_headers(client: TestClient, db_session: Session) -> dict[str, str]:
    other = User(
        email="other@example.com",
        password_hash=hash_password("secretpass123"),
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    from app.auth.security import create_access_token

    token = create_access_token(other.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_id(client: TestClient, auth_headers: dict[str, str]):
    from jose import jwt

    from app.config import settings

    token = auth_headers["Authorization"].removeprefix("Bearer ")
    payload = jwt.decode(
        token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
    )
    return payload["sub"]


@pytest.fixture
def funded_accounts(
    client: TestClient,
    db_session: Session,
    auth_headers: dict[str, str],
    user_id: str,
):
    import uuid
    from decimal import Decimal

    sender = Account(
        user_id=uuid.UUID(user_id),
        account_number="ACC-SENDER001",
        balance=Decimal("1000.00"),
        currency="USD",
    )
    receiver = Account(
        user_id=uuid.UUID(user_id),
        account_number="ACC-RECEIVER01",
        balance=Decimal("100.00"),
        currency="USD",
    )
    db_session.add(sender)
    db_session.add(receiver)
    db_session.commit()
    db_session.refresh(sender)
    db_session.refresh(receiver)
    return {
        "sender": sender.account_number,
        "receiver": receiver.account_number,
        "sender_id": str(sender.id),
        "receiver_id": str(receiver.id),
    }
