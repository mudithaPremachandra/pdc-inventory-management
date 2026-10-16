# Architecture

## The big picture

```
                    ┌───────────────────────────── WRITE SIDE ─────────────────────────────┐
  CLI ── command ──►│ command-api :8001 → CommandHandler → Product/User aggregate           │
 (cli/)  (HTTP)     │ (commands/api.py)   (handlers.py)    (domain/product.py, auth/user.py)│
   │                │                         │ load (replay)          │ new events         │
   │                │                         ▼                        ▼                    │
   │                │              EventStore: public.events  (append-only, versioned)      │
   │                └──────────────────────────┬────────────────────────────────────────────┘
   │                                           │ pg_notify('events_appended')
   │                                           ▼
   │                               projector (projections/projector.py)
   │                                 reads after checkpoint, applies handlers,
   │                                 saves checkpoint in the same transaction
   │                                           │
   │                ┌──────────────────────────▼─────────── READ SIDE ──────────────────────┐
   └─── query ─────►│ query-api :8002 → queries.py → read.products / read.stock_movements   │
        (HTTP)      │ (queries/api.py)               read.users / read.projection_checkpoints│
                    │                 time_travel.py → replays public.events up to a time   │
                    └───────────────────────────────────────────────────────────────────────┘
```

| Container | Code | Role |
|---|---|---|
| `postgres` | `db/init/*.sql` | Event store (`public.events`) + read models (`read.*`) |
| `command-api` | `inventory.commands.api` (+ `inventory.auth.routes`) | Write side. Accepts commands, appends events |
| `projector` | `inventory.projections.projector` | Turns events into read-model rows |
| `query-api` | `inventory.queries.api` | Read side. Answers queries from the read models |
| `cli` | `inventory.cli.main` | Command-line user interface |
| `postgres-test`, `tests` | `tests/` | Throwaway DB + pytest (profile `test`) |

## Following one command end-to-end: `receive CBL-001 50`

1. **CLI** (`cli/commands.py::receive`) sends `POST /products/CBL-001/receive {"quantity": 50}` to the command-api with the JWT.
2. **Auth** (`auth/permissions.py::require`) verifies the token, loads `user-<name>` from the event store and checks the role has `stock:receive`.
3. **Command API** (`commands/api.py`) builds a `ReceiveStock` command object and passes it to the `CommandHandler`.
4. **Handler** (`commands/handlers.py::execute`):
   1. `repository.load(Product, "CBL-001")`: reads every event of stream `product-CBL-001` and replays them through `Product.on_*` methods. The product now knows its quantity and its version (say 2).
   2. `product.receive(50)`: checks the rules (exists, not discontinued, quantity > 0) and records `StockReceived`.
   3. `repository.save(product)` → `EventStore.append(..., expected_version=2)`: inside one transaction it takes the append lock, checks the stream is still at version 2, and inserts version 3. If someone else got there first it raises `ConcurrencyError`, and the handler retries from step 1.
5. Postgres fires `pg_notify('events_appended', '17')`.
6. The command-api answers **202** `{"stream_id": "product-CBL-001", "version": 3, "global_position": 17, "events": ["StockReceived"]}`.
7. **Projector** wakes up, reads events after its checkpoint, runs `projections/handlers.py::stock_received` (`UPDATE read.products SET quantity = quantity + 50 … WHERE version < 3` and inserts a `read.stock_movements` row), then moves the checkpoint to 17, all in one transaction.
8. **CLI** polls `GET /status` on the query-api until `checkpoint ≥ 17` ("read model updated"), so the user's next `product CBL-001` shows the new quantity (*read-your-writes*).

## Event catalogue

| Stream | Event | Data |
|---|---|---|
| `product-<SKU>` | `ProductRegistered` | sku, name, category, unit_price, reorder_level |
| | `ProductDetailsUpdated` | sku + only the changed fields |
| | `StockReceived` | sku, quantity, reference |
| | `StockDispatched` | sku, quantity, reference |
| | `StockAdjusted` | sku, quantity_change (±), reason |
| | `ProductDiscontinued` | sku, reason |
| `user-<username>` | `UserRegistered` | username, role, password_hash |
| | `UserRoleChanged` | username, old_role, new_role |
| | `UserPasswordChanged` | username, password_hash |
| | `UserDeactivated` / `UserReactivated` | username |

Every event row also has `metadata` = `{user, command, correlation_id}` and `occurred_at`.

## Key design decisions (and the viva question each one answers)

| Decision | Why |
|---|---|
| One aggregate = one stream (`product-<SKU>`) | The aggregate is the consistency boundary. Rules like "no negative stock" only need that one stream |
| `UNIQUE(stream_id, version)` + `expected_version` | Optimistic concurrency, so two clerks can't both sell the last item |
| Global advisory lock on append | `global_position` always grows in commit order, so the projector can't skip an event that committed late |
| Triggers block UPDATE/DELETE/TRUNCATE on `events` | History is immutable. Mistakes are fixed with *new* events (e.g. `StockAdjusted`) |
| Projection handlers guarded by `version < event.version` | Idempotent. Replaying an event twice is harmless |
| Checkpoint saved in the same transaction as the read-model update | No lost or double-applied events after a crash |
| Rebuild in one transaction | Readers see old data until the new data is complete |
| Separate command-api / query-api containers | Each side can be scaled, secured and deployed on its own |
| Same Postgres for both stores | Simpler for a student project; the code never joins across them, so they could be split |
| Auth checks current role from the user's event stream | Role changes and deactivations apply immediately, not when the JWT expires |
| Password hashes redacted in the event log endpoint | Sensitive data stays on the write side |

## Known limitations (good "what would you improve?" answers)
* No **snapshots**: a product with 100,000 events would be slow to load. Fix: store a snapshot every N events.
* Events can't be deleted, so a GDPR "forget me" request needs **crypto-shredding** (encrypt personal data per user, delete the key).
* No **event versioning/upcasting** yet. Changing an event's shape later needs an upcaster.
* One projector for all read models. Larger systems run one projector per read model with its own checkpoint.
* No idempotency keys on commands: re-sending the same HTTP request twice receives twice.
