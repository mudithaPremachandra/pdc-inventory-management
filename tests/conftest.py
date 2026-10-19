"""Shared pytest fixtures.

Unit tests need nothing. Integration and e2e tests need PostgreSQL at DATABASE_URL;
they are skipped automatically when it can't be reached. In Docker:

    docker compose --profile test run --rm tests
"""

import io
import threading
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from rich.console import Console

from inventory.config import settings

TESTS_DIR = Path(__file__).parent


def _database_reachable() -> bool:
    try:
        psycopg.connect(settings.database_url, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


def pytest_collection_modifyitems(config, items):
    """Mark tests by folder, and skip the DB-backed ones when there is no database."""
    needs_db = []
    for item in items:
        parts = Path(str(item.fspath)).relative_to(TESTS_DIR).parts
        if parts[0] in ("integration", "e2e"):
            item.add_marker(getattr(pytest.mark, parts[0]))
            needs_db.append(item)
    if needs_db and not _database_reachable():
        skip = pytest.mark.skip(reason=f"PostgreSQL not reachable at {settings.database_url}")
        for item in needs_db:
            item.add_marker(skip)


# --- database ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pool():
    from inventory.db import close_pool, get_pool

    yield get_pool()
    close_pool()


@pytest.fixture
def clean_db(pool):
    """Empty every table before a test.

    The events table refuses TRUNCATE (append-only trigger). `session_replication_role
    = replica` switches triggers off for this connection only - a superuser-only escape
    hatch that is acceptable for a throwaway test database and nowhere else.
    """
    with pool.connection() as conn:
        conn.execute("SET session_replication_role = replica")
        conn.execute("TRUNCATE events RESTART IDENTITY")
        conn.execute("TRUNCATE read.products, read.stock_movements, read.users, read.projection_checkpoints")
        conn.execute("SET session_replication_role = DEFAULT")
    return pool


@pytest.fixture
def store(clean_db):
    from inventory.eventstore.store import EventStore

    return EventStore(clean_db)


@pytest.fixture
def handler(store):
    from inventory.commands.handlers import CommandHandler
    from inventory.eventstore.repository import AggregateRepository

    return CommandHandler(AggregateRepository(store))


@pytest.fixture
def project(clean_db):
    """Call project() to run the projector until it has applied every event."""
    from inventory.projections.projector import catch_up

    return lambda: catch_up(clean_db)


@pytest.fixture
def running_projector(clean_db):
    """The projector running in a background thread, like the real `projector` service."""
    from inventory.projections.projector import catch_up

    stop = threading.Event()

    def loop():
        while not stop.is_set():
            catch_up(clean_db)
            stop.wait(0.05)

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()
    yield
    stop.set()
    thread.join(timeout=5)


# --- APIs -------------------------------------------------------------------------------


@pytest.fixture
def command_api(clean_db):
    from inventory.commands.api import app

    with TestClient(app) as client:  # `with` runs startup, which seeds the admin user
        yield client


@pytest.fixture
def query_api(clean_db):
    from inventory.queries.api import app

    with TestClient(app) as client:
        yield client


def _login(command_api, username, password) -> dict:
    response = command_api.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin(command_api) -> dict:
    """Authorization headers for the seeded admin."""
    return _login(command_api, settings.admin_username, settings.admin_password)


@pytest.fixture
def user_with_role(command_api, admin):
    """Factory: user_with_role("clerk") -> auth headers of a fresh user with that role."""
    counter = iter(range(1, 1000))

    def make(role: str) -> dict:
        username = f"{role}{next(counter)}"
        r = command_api.post("/users", headers=admin, json={"username": username, "password": "password1", "role": role})
        assert r.status_code == 202, r.text
        return _login(command_api, username, "password1")

    return make


# --- CLI --------------------------------------------------------------------------------


@pytest.fixture
def cli(command_api, query_api, running_projector):
    """A CLI session wired to the in-process APIs. cli("receive A 1") -> (exit_code, output)."""
    from inventory.cli import commands  # noqa: F401
    from inventory.cli.client import ApiClient, Session
    from inventory.cli.main import run_line

    out = io.StringIO()
    session = Session(
        api=ApiClient(command_http=command_api, query_http=query_api),
        console=Console(file=out, width=250),
        persist=False,
    )

    def run(line: str) -> tuple[int, str]:
        out.seek(0)
        out.truncate()
        code = run_line(session, line)
        return code, out.getvalue()

    run.session = session
    return run

