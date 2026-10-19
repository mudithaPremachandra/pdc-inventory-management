"""Rebuild inventory read models by replaying the event log."""

from psycopg_pool import ConnectionPool

from inventory.eventstore.store import EventStore
from inventory.projections.handlers import apply_event
from inventory.projections.projector import (
    PROJECTION_LOCK_KEY,
    PROJECTION_NAME,
    save_checkpoint,
)

REBUILD_TABLES = (
    "read.products",
    "read.stock_movements",
    "read.users",
)


def rebuild(pool: ConnectionPool) -> dict:
    """Rebuild all read models atomically from stored events."""
    store = EventStore(pool)
    replayed = 0
    position = 0

    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (PROJECTION_LOCK_KEY,),
        )

        # The old read models remain visible until this transaction commits.
        conn.execute(
            f"TRUNCATE TABLE {', '.join(REBUILD_TABLES)}"
        )

        save_checkpoint(conn, 0)

        with conn.cursor() as cur:
            while True:
                events = store.read_all(
                    after_position=position,
                    limit=500,
                    conn=conn,
                )

                if not events:
                    break

                for event in events:
                    apply_event(cur, event)

                position = events[-1].global_position
                replayed += len(events)

            save_checkpoint(conn, position)

    return {
        "replayed_events": replayed,
        "checkpoint": position,
    }