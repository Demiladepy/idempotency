from collections.abc import Generator
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import models as _models  # noqa: F401 — register ORM tables
from app.auth.security import hash_password
from app.database import Base, get_db
from app.main import app
from app.models import Account, IdempotencyRecord, Payment, User


def _postgres_url() -> str | None:
    for key in ("TEST_DATABASE_URL", "DATABASE_URL"):
        url = os.environ.get(key, "")
        if url.startswith("postgresql"):
            return url
    return None


@pytest.fixture
def postgres_engine():
    url = _postgres_url()
    if url is None:
        pytest.skip("Postgres DATABASE_URL required for race condition tests")

    engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=10,
    )
    Base.metadata.create_all(engine)
    yield engine
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE idempotency_records, payments, accounts, users "
                "RESTART IDENTITY CASCADE"
            )
        )
    engine.dispose()


@pytest.fixture
def postgres_client(postgres_engine) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(
        autocommit=False, autoflush=False, bind=postgres_engine
    )

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def postgres_auth_headers(postgres_client: TestClient) -> dict[str, str]:
    email = f"race-{uuid.uuid4()}@example.com"
    postgres_client.post(
        "/auth/register",
        json={"email": email, "password": "secretpass123"},
    )
    login_response = postgres_client.post(
        "/auth/login",
        json={"email": email, "password": "secretpass123"},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def postgres_funded_accounts(
    postgres_client: TestClient,
    postgres_engine,
    postgres_auth_headers: dict[str, str],
) -> dict[str, str]:
    from decimal import Decimal

    from jose import jwt

    from app.config import settings

    token = postgres_auth_headers["Authorization"].removeprefix("Bearer ")
    user_id = uuid.UUID(
        jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])["sub"]
    )

    session = sessionmaker(bind=postgres_engine)()
    sender = Account(
        user_id=user_id,
        account_number=f"ACC-SEND-{uuid.uuid4().hex[:8].upper()}",
        balance=Decimal("1000.00"),
        currency="USD",
    )
    receiver = Account(
        user_id=user_id,
        account_number=f"ACC-RECV-{uuid.uuid4().hex[:8].upper()}",
        balance=Decimal("0.00"),
        currency="USD",
    )
    session.add(sender)
    session.add(receiver)
    session.commit()
    session.refresh(sender)
    session.refresh(receiver)
    session.close()

    return {
        "sender": sender.account_number,
        "receiver": receiver.account_number,
        "sender_id": str(sender.id),
        "receiver_id": str(receiver.id),
    }


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
    IdempotencyRecord.__table__.create(engine)
    yield engine
    IdempotencyRecord.__table__.drop(engine)
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
def payment_headers(auth_headers: dict[str, str]) -> dict[str, str]:
    return {**auth_headers, "Idempotency-Key": str(uuid.uuid4())}


def make_payment_headers(auth_headers: dict[str, str], idempotency_key: str | None = None) -> dict[str, str]:
    return {**auth_headers, "Idempotency-Key": idempotency_key or str(uuid.uuid4())}


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
