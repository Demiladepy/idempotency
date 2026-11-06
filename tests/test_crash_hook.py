import os

import pytest

from app.crash import AFTER_CHARGE_FLUSH, crash_after
from tests.conftest import make_payment_headers


def test_crash_after_is_a_noop_without_the_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRASH_AFTER", raising=False)
    calls: list[int] = []
    monkeypatch.setattr("app.crash.os._exit", lambda code: calls.append(code))

    crash_after(AFTER_CHARGE_FLUSH)

    assert calls == []


def test_crash_after_hard_exits_on_the_named_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRASH_AFTER", "after_charge_flush")
    calls: list[int] = []
    monkeypatch.setattr("app.crash.os._exit", lambda code: calls.append(code))

    crash_after("somewhere_else")
    crash_after(AFTER_CHARGE_FLUSH)

    assert calls == [1]
    assert os.environ["CRASH_AFTER"] == "after_charge_flush"


def test_charge_committed_is_the_pre_commit_flush(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRASH_AFTER", "charge_committed")
    calls: list[int] = []
    monkeypatch.setattr("app.crash.os._exit", lambda code: calls.append(code))

    crash_after(AFTER_CHARGE_FLUSH)

    assert calls == [1]


def test_payment_reaches_the_crash_point(client, auth_headers, funded_accounts, monkeypatch):
    seen: list[str] = []

    def record(point: str) -> None:
        seen.append(point)

    monkeypatch.setattr("app.services.payments.crash_after", record)
    response = client.post(
        "/payments",
        json={
            "from_account": funded_accounts["sender"],
            "to_account": funded_accounts["receiver"],
            "amount": "15.00",
            "currency": "USD",
        },
        headers=make_payment_headers(auth_headers),
    )

    assert response.status_code == 201
    assert seen == [AFTER_CHARGE_FLUSH]
