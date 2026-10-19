"""The event store against a real PostgreSQL: ordering, concurrency, immutability."""

import threading
from datetime import timedelta

import psycopg
import pytest

from inventory.commands.commands import DispatchStock, ReceiveStock, RegisterProduct
from inventory.domain.errors import ConcurrencyError, InsufficientStock
from inventory.eventstore.store import NewEvent


def _append(store, stream, expected, *types):
    return store.append(stream, "test", expected, [NewEvent(t, {"n": i}) for i, t in enumerate(types)])


def test_append_then_load_returns_events_in_version_order(store):
    _append(store, "s-1", 0, "A", "B")
    _append(store, "s-1", 2, "C")
    events = store.load_stream("s-1")
    assert [(e.version, e.event_type) for e in events] == [(1, "A"), (2, "B"), (3, "C")]
    assert store.stream_version("s-1") == 3


def test_wrong_expected_version_is_rejected_and_writes_nothing(store):
    _append(store, "s-1", 0, "A")
    with pytest.raises(ConcurrencyError):
        _append(store, "s-1", 0, "B")  # we think the stream is new, but it isn't
    assert store.stream_version("s-1") == 1


def test_read_all_follows_global_position_across_streams(store):
    _append(store, "s-1", 0, "A")
    _append(store, "s-2", 0, "B")
    _append(store, "s-1", 1, "C")
    events = store.read_all()
    assert [e.event_type for e in events] == ["A", "B", "C"]
    assert [e.event_type for e in store.read_all(after_position=events[0].global_position)] == ["B", "C"]


def test_metadata_is_stored(store):
    store.append("s-1", "test", 0, [NewEvent("A", {})], {"user": "admin"})
    assert store.load_stream("s-1")[0].metadata == {"user": "admin"}


@pytest.mark.parametrize("sql", [
    "UPDATE events SET event_type = 'Hacked'",
    "DELETE FROM events",
    "TRUNCATE events",
])
def test_events_table_is_append_only(store, clean_db, sql):
    _append(store, "s-1", 0, "A")
    with clean_db.connection() as conn, pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        conn.execute(sql)
    assert store.stream_version("s-1") == 1


def test_load_stream_until_a_point_in_time(store):
    first = _append(store, "s-1", 0, "A")[0]
    _append(store, "s-1", 1, "B")
    assert [e.event_type for e in store.load_stream("s-1", until=first.occurred_at)] == ["A"]
    assert store.load_stream("s-1", until=first.occurred_at - timedelta(seconds=1)) == []


def test_concurrent_dispatches_never_oversell(handler, store):
    """10 clerks dispatch 1 unit at the same moment, but only 5 are in stock.

    Optimistic concurrency + retry means every dispatch is decided against the latest
    stock level, so at most 5 succeed and stock never goes below zero.
    """
    handler.handle(RegisterProduct("RACE-1", "Race", "1.00", 0), "test")
    handler.handle(ReceiveStock("RACE-1", 5), "test")

    outcomes, lock = [], threading.Lock()
    start = threading.Barrier(10)

    def clerk():
        start.wait()
        try:
            handler.handle(DispatchStock("RACE-1", 1), "test")
            result = "ok"
        except InsufficientStock:
            result = "insufficient"
        except ConcurrencyError:
            result = "conflict"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=clerk) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    from inventory.domain.product import Product
    from inventory.eventstore.repository import AggregateRepository

    product = AggregateRepository(store).load(Product, "RACE-1")
    successes = outcomes.count("ok")
    assert len(outcomes) == 10
    assert 1 <= successes <= 5
    assert product.quantity_on_hand == 5 - successes >= 0

