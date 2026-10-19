"""Project stored events into inventory read models."""

import logging
import time

import psycopg
from psycopg_pool import ConnectionPool

from inventory.config import settings
from inventory.db import get_pool
from inventory.eventstore.store import EventStore
from inventory.projections.handlers import apply_event

log = logging.getLogger(__name__)

PROJECTION_NAME = "inventory_read_models"
PROJECTION_LOCK_KEY = 7_000_002
BATCH_SIZE = 500


def save_checkpoint(conn, position: int) -> None:
    """Save progress in the current transaction."""
    conn.execute(
        """
        INSERT INTO read.projection_checkpoints
            (projection_name, last_position, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (projection_name)
        DO UPDATE SET
            last_position = EXCLUDED.last_position,
            updated_at = now()
        """,
        (PROJECTION_NAME, position),
    )


def run_once(pool: ConnectionPool) -> int:
    """Process one batch of events and commit updates atomically."""
    store = EventStore(pool)

    with pool.connection() as conn, conn.transaction():
        conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (PROJECTION_LOCK_KEY,),
        )

        row = conn.execute(
            """
            SELECT last_position
            FROM read.projection_checkpoints
            WHERE projection_name = %s
            """,
            (PROJECTION_NAME,),
        ).fetchone()

        position = row["last_position"] if row else 0

        with conn.cursor() as cur:
            events = store.read_all(
                after_position=position,
                limit=BATCH_SIZE,
                conn=conn,
            )

            if not events:
                return 0

            for event in events:
                apply_event(cur, event)

            position = events[-1].global_position
            save_checkpoint(conn, position)

        return len(events)


def catch_up(pool: ConnectionPool) -> int:
    """Apply batches until no events remain."""
    total = 0

    while True:
        applied = run_once(pool)
        if applied == 0:
            return total
        total += applied


def run_forever() -> None:
    """Run the projector worker and listen for new events."""
    pool = get_pool()

    with psycopg.connect(
        settings.database_url,
        autocommit=True,
    ) as listener:
        listener.execute("LISTEN events_appended")
        log.info("Projector started.")

        while True:
            try:
                catch_up(pool)
            except psycopg.Error:
                log.exception("Projection failed; retrying.")

            for _ in listener.notifies(
                timeout=settings.projector_poll_seconds,
                stop_after=1,
            ):
                pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run_forever()
    