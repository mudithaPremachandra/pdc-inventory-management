# Test Plan: Inventory Management (CQRS + Event Sourcing)

## 1. Goal
Show that (a) the business rules hold, (b) the CQRS split behaves as designed (writes go to the event store, reads come from projections that catch up), and (c) event-sourcing guarantees hold: append-only history, optimistic concurrency, replay, rebuild and time travel.

## 2. Test levels

| Level | Folder | Needs DB? | What it proves | Owner |
|---|---|---|---|---|
| Unit | `tests/unit` | no | Aggregates enforce rules (given events / when command / then events), events serialise losslessly, RBAC matrix, CLI parsing/help | Sarangi |
| Integration | `tests/integration` | yes | Event store ordering, optimistic concurrency, append-only trigger, projector idempotency, rebuild = live state | Kavindi |
| End-to-end | `tests/e2e` | yes | Real HTTP APIs + real CLI commands, auth/RBAC, read-your-writes, time travel | Kavindi |
| Manual | this document §5 | full stack | Viva demonstration script | Sarangi |

Run everything: `docker compose --profile test run --rm tests` (or `scripts/run-tests.ps1` / `scripts/run-tests.sh`).
Run only the unit tests without Docker: `pip install -r requirements.txt` then `pytest tests/unit` (the DB tests are skipped automatically).

### Unit test style: Given / When / Then
```python
def test_dispatch_more_than_in_stock_is_refused():
    with pytest.raises(InsufficientStock):
        when(given(REGISTERED, StockReceived(SKU, 10), StockDispatched(SKU, 8)),
             lambda p: p.dispatch(3))
```
*Given* is a list of past events (there is no database row to set up, because history is the state). *When* calls one command method. *Then* checks either the new events recorded or the error raised.

## 3. Requirements traceability

| # | Requirement | Automated test(s) | Manual |
|---|---|---|---|
| R1 | Register products with a unique SKU, a price ≥ 0 and a reorder level ≥ 0 | `test_product_aggregate.py::test_register_*`, `test_cannot_register_the_same_sku_twice`, `test_api_flow.py::test_validation_errors_are_reported` | TC-02 |
| R2 | Receive / dispatch stock; never dispatch more than on hand | `test_dispatch_*`, `test_api_flow.py::test_full_inventory_flow` | TC-03, TC-04 |
| R3 | Adjust stock only with a reason; never below zero | `test_adjust_*` | TC-05 |
| R4 | Discontinued products refuse movements but keep history | `test_discontinued_product_refuses_*`, `test_projected_state_matches_the_events` | TC-10 |
| R5 | Every change is stored as an immutable event | `test_events_table_is_append_only`, `test_events_are_immutable` | TC-07 |
| R6 | Concurrent writers cannot corrupt stock | `test_concurrent_dispatches_never_oversell`, `test_wrong_expected_version_is_rejected_and_writes_nothing` | (none) |
| R7 | Reads come from projections, which are eventually consistent | `test_read_model_is_empty_until_the_projector_runs`, `test_cli_session_end_to_end` | TC-08 |
| R8 | Projections can be rebuilt from events; replay is idempotent | `test_rebuild_reproduces_the_live_read_model`, `test_replaying_the_same_events_twice_changes_nothing` | TC-09 |
| R9 | State at any past time can be reconstructed | `test_time_travel_replays_events_up_to_a_moment` | TC-06 |
| R10 | Login required; role-based permissions | `test_access_control.py::*`, `test_user_and_auth.py::test_role_permissions` | TC-11, TC-12 |
| R11 | Deactivation/role change applies immediately | `test_deactivation_blocks_an_existing_token_immediately`, `test_role_change_applies_without_logging_in_again` | TC-12 |
| R12 | Password hashes never leave the write side | `test_event_log_hides_password_hashes`, `test_password_hash_verifies_and_is_salted` | TC-07 |
| R13 | CLI: `help` lists every command; bad input gives a clear message | `test_cli_parsing.py::*` | TC-01 |

## 4. Environments and data
* Automated: `postgres-test` container on tmpfs (memory only). Every DB test starts from empty tables (`clean_db` fixture).
* Manual: the normal stack (`docker compose up -d --build`), admin user `admin` / `admin123` from `.env`.
* To reset the manual environment completely: `docker compose down -v` (deletes the volume, including **all events**).

## 5. Manual test cases (viva demo script)
Start: `docker compose up -d --build`, then `docker compose run --rm cli`.

| ID | Steps | Expected result |
|---|---|---|
| TC-01 | `help`, then `help receive`, then `teleport` | Grouped command table; usage, arguments, permission and example for `receive`; "unknown command" for `teleport` |
| TC-02 | `login admin`, then `product-add CBL-001 "USB-C cable" --price 4.99 --reorder-level 20 --category cables` | `ProductRegistered → product-CBL-001 (version 1, …)` and "read model updated" |
| TC-03 | `receive CBL-001 50 --ref PO-1` then `product CBL-001` | `StockReceived` version 2; quantity 50 |
| TC-04 | `dispatch CBL-001 80` | Refused: "only 50 in stock"; no event appended (check `events`) |
| TC-05 | `adjust CBL-001 -2 --reason "damaged"`; then `adjust CBL-001 -1000 --reason x` | First accepted (qty 48); second refused, would be negative |
| TC-06 | Wait a minute, `dispatch CBL-001 10`, then `stock-at CBL-001 30s` | Shows the quantity *before* the dispatch (48), rebuilt by replaying events |
| TC-07 | `events --stream product-CBL-001` and `events --stream user-admin` | Full ordered history with versions and user; password hash shown as `***` |
| TC-08 | In another terminal `docker compose stop projector`; in the CLI `receive CBL-001 5`, `product CBL-001`, `status` | Command succeeds, but the CLI warns that the read model has not caught up; `product` shows the old quantity; `status` shows lag 1. Then `docker compose start projector` and `status` shows lag 0 and the new quantity |
| TC-09 | `rebuild-projections`, then `products` | "replayed N events"; product list identical to before |
| TC-10 | `product-discontinue CBL-001 --reason old`, `receive CBL-001 1`, `products --all` | Receive refused ("discontinued"); product listed with status discontinued; `history` still shows all movements |
| TC-11 | `user-add nimal --role viewer -p secret99`, `logout`, `login nimal`, `products`, `receive CBL-001 1` | Viewer can list products; receive refused with "not allowed (needs 'stock:receive')" |
| TC-12 | As admin in a second CLI: `user-deactivate nimal`; back in nimal's CLI: `products` | Refused immediately ("account is disabled") without waiting for the token to expire |

## 6. Entry / exit criteria
* **Entry:** stack builds; `docker compose ps` shows all services up/healthy.
* **Exit:** all automated tests pass; TC-01…TC-12 pass; no open defect of severity High.

## 7. Defect reporting
Record: test ID, steps, expected vs actual, output of `events --limit 20` and `status` (the event log usually explains the bug), and `docker compose logs <service>`.

