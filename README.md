# Inventory Management: CQRS + Event Sourcing

A command-line inventory system built to show **Command Query Responsibility Segregation (CQRS)** and **Event Sourcing**.

* Every change (product registered, stock received or dispatched…) is stored as an **immutable event** in an append-only event store.
* The **write side** (`command-api`) rebuilds aggregates from their events, checks business rules and appends new events with optimistic concurrency.
* A **projector** turns events into **read models** (plain tables).
* The **read side** (`query-api`) answers queries from those read models. It can also **time-travel** by replaying events.
* The **CLI** is the user interface: type commands, and `help` lists them all.

Stack: Python 3.12 · FastAPI · PostgreSQL 16 · psycopg 3 · JWT + bcrypt · Rich · pytest · Docker Compose.
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and [docs/TEST_PLAN.md](docs/TEST_PLAN.md) for testing and the demo script.

## Quick start

Requirements: Docker Desktop (or Docker Engine + Compose v2).

```bash
cp .env.example .env              # optional: change passwords / JWT secret
docker compose up -d --build      # postgres, command-api, projector, query-api
docker compose run --rm cli       # open the CLI (also starts anything not running yet)
```

Or install the `inventory` command once with `scripts\setup.cmd` (Windows) or `sh scripts/setup.sh` (Git Bash, macOS, Linux). It adds the command to your PATH and starts the system. Then, from any folder in a new terminal: `inventory` (open the CLI), `inventory start`, `inventory stop`, `inventory --help` for the rest.

```
inventory(not logged in)> login admin            # password: admin123 (from .env)
inventory(admin)> help
inventory(admin)> product-add CBL-001 "USB-C cable" --price 4.99 --reorder-level 20 --category cables
✔ ProductRegistered → product-CBL-001 (version 1, position 2)
read model updated
inventory(admin)> receive CBL-001 50 --ref PO-1001
inventory(admin)> dispatch CBL-001 80
✖ cannot dispatch 80 of CBL-001: only 50 in stock
inventory(admin)> dispatch CBL-001 35 --ref SO-2001
inventory(admin)> history CBL-001
inventory(admin)> low-stock
inventory(admin)> stock-at CBL-001 1m            # time travel: state 1 minute ago
inventory(admin)> events --stream product-CBL-001
```

Single commands also work, which is handy for scripts: `docker compose run --rm cli inventory help`.

### Show eventual consistency
```bash
docker compose stop projector     # read side stops updating
#   in the CLI: receive CBL-001 5   -> warns the read model hasn't caught up
#               status              -> lag: 1 event(s)
docker compose start projector    # catches up within a moment
```

### Useful commands
| What | Command |
|---|---|
| Logs of one service | `docker compose logs -f projector` |
| Look at the raw events | `docker compose exec postgres psql -U inventory -c "SELECT global_position, stream_id, version, event_type, data FROM events"` |
| Run all tests | `docker compose --profile test run --rm tests` or `scripts/run-tests.ps1` / `sh scripts/run-tests.sh` |
| Stop everything | `docker compose down` (keeps data) |
| Delete all data | `docker compose down -v` (removes the volume, **including every event**) |
| API docs (Swagger) | http://localhost:8001/docs (write side), http://localhost:8002/docs (read side) |

Default users: only `admin` / `admin123` is created at startup. Add more with `user-add <name> --role admin|manager|clerk|viewer`.

| Role | Can |
|---|---|
| admin | everything, including users and `rebuild-projections` |
| manager | products, all stock movements, reports, event log |
| clerk | receive and dispatch stock, view products |
| viewer | view products and reports |

## Project layout

```
db/init/                SQL: event store table + triggers, read-model tables
src/inventory/
  domain/               events, Product aggregate, business rules
  eventstore/           EventStore (append/load/read_all) + AggregateRepository
  commands/             commands, command handler, command-api (write side)
  projections/          projector worker, projection handlers, rebuild
  queries/              query handlers, time travel, query-api (read side)
  auth/                 User aggregate, passwords, JWT, role-based permissions
  cli/                  REPL, command registry/help, API client
tests/unit|integration|e2e
docs/                   architecture, test plan
```

## Team and ownership

| Member | Part | Files (the full brief is in the first file listed) |
|---|---|---|
| **Muditha** | Team lead / tech lead | `README.md`, `docs/ARCHITECTURE.md`, `.gitattributes`, the `__init__.py` package files |
| **Disaan** | Domain model | `src/inventory/domain/product.py`, `events.py`, `aggregate.py`, `errors.py` |
| **Geethika** | Command side (write) | `src/inventory/commands/handlers.py`, `commands.py`, `api.py` |
| **Janani** | Projections | `src/inventory/projections/projector.py`, `handlers.py`, `rebuild.py` |
| **Kasun** | CLI frontend | `src/inventory/cli/main.py`, `registry.py`, `commands.py`, `client.py` |
| **Kasunara** | Database / event store | `db/init/001_event_store.sql`, `002_read_models.sql`, `src/inventory/db.py`, `src/inventory/eventstore/store.py`, `repository.py` |
| **Sandun** | Authentication and access management | `src/inventory/auth/permissions.py`, `user.py`, `passwords.py`, `tokens.py`, `routes.py` |
| **Sanjaya** | Query side (read) and Docker deployment | `src/inventory/queries/queries.py`, `time_travel.py`, `api.py`, `src/inventory/config.py`, `docker-compose.yml`, `Dockerfile`, `.dockerignore`, `.env.example`, `.gitignore`, `requirements.txt`, `pyproject.toml` |
| **Kavindi** | Test automation | `tests/conftest.py`, `tests/integration/*`, `tests/e2e/*`, `scripts/run-tests.*`, `.github/workflows/tests.yml` |
| **Sarangi** | Testing (unit tests, test plan) | `docs/TEST_PLAN.md`, `tests/unit/*` |
