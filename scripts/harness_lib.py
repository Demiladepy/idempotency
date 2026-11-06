"""Process and database helpers shared by the failure-injection scripts."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

DEFAULT_DATABASE_URL = "postgresql://payments:payments@localhost:5432/payments_db"
DEFAULT_JWT_SECRET = "dev-secret-change-before-production"
REPO_ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def server_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url()
    env["APP_ENV"] = env.get("APP_ENV", "development")
    env["JWT_SECRET"] = env.get("JWT_SECRET", DEFAULT_JWT_SECRET)
    env["JWT_ALGORITHM"] = env.get("JWT_ALGORITHM", "HS256")
    env["JWT_EXPIRE_MINUTES"] = env.get("JWT_EXPIRE_MINUTES", "60")
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("CRASH_AFTER", None)
    if extra:
        env.update(extra)
    return env


def ensure_schema() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=server_env(),
        check=True,
    )


def start_server(
    port: int,
    extra_env: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> tuple[subprocess.Popen[bytes], object]:
    log_file = (log_path or REPO_ROOT / "harness-server.log").open("wb")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=server_env(extra_env),
        stdin=subprocess.DEVNULL,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return proc, log_file


def log_tail(log_path: Path, lines: int = 40) -> str:
    if not log_path.exists():
        return ""
    content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(content[-lines:])


def wait_healthy(
    base_url: str,
    proc: subprocess.Popen[bytes],
    log_path: Path,
    timeout: float = 30,
) -> None:
    deadline = time.time() + timeout
    last_error = "no response"
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"server exited early ({proc.returncode})\n{log_tail(log_path)}"
            )
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
            last_error = f"HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(0.2)
    stop_server(proc)
    raise RuntimeError(f"server did not become healthy: {last_error}\n{log_tail(log_path)}")


def stop_server(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=15,
        )
    else:
        proc.kill()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def wait_port_free(port: int, timeout: float = 15) -> None:
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} is still accepting connections")


def release_open_transactions() -> None:
    """Drop backends left behind by os._exit.

    A hard exit closes the socket, but Postgres can keep that transaction's
    row locks until it notices the disconnect. The retry would then block
    on SELECT FOR UPDATE.
    """
    eng = create_engine(database_url(), pool_pre_ping=True)
    try:
        with eng.begin() as conn:
            conn.execute(
                text(
                    """
                    SELECT pg_terminate_backend(pid)
                    FROM pg_stat_activity
                    WHERE datname = current_database()
                      AND pid <> pg_backend_pid()
                      AND state IS DISTINCT FROM 'idle'
                    """
                )
            )
    finally:
        eng.dispose()


def fund_account(account_number: str, balance: str = "100000.00") -> None:
    eng = create_engine(database_url(), pool_pre_ping=True)
    try:
        with eng.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE accounts SET balance = :balance "
                    "WHERE account_number = :number"
                ),
                {"balance": balance, "number": account_number},
            )
            if result.rowcount != 1:
                raise RuntimeError(f"could not fund account {account_number}")
    finally:
        eng.dispose()


def count_payments(from_account: str) -> int:
    eng = create_engine(database_url(), pool_pre_ping=True)
    try:
        with eng.connect() as conn:
            count = conn.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM payments AS p
                    JOIN accounts AS a ON a.id = p.from_account_id
                    WHERE a.account_number = :number
                    """
                ),
                {"number": from_account},
            ).scalar_one()
    finally:
        eng.dispose()
    return int(count)


def prepare_sender(base_url: str) -> dict[str, str]:
    email = f"harness-{uuid.uuid4()}@example.com"
    password = "secretpass123"
    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        register = client.post(
            "/auth/register",
            json={"email": email, "password": password},
        )
        register.raise_for_status()
        login = client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        login.raise_for_status()
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        sender = client.post("/accounts", json={"currency": "USD"}, headers=headers)
        sender.raise_for_status()
        receiver = client.post("/accounts", json={"currency": "USD"}, headers=headers)
        receiver.raise_for_status()

    sender_number = sender.json()["account_number"]
    fund_account(sender_number)
    return {
        "token": token,
        "sender": sender_number,
        "receiver": receiver.json()["account_number"],
    }
