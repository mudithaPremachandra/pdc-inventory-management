


import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg import Connection
from psycopg_pool import ConnectionPool

from inventory.domain.errors import ConcurrencyError

# Every append takes this lock for the rest of its transaction, so appends commit
# one at a time and global_position always grows in commit order. Without it, a
# slow transaction holding position 10 could commit after one holding 11, and the
# projector (which had already moved past 11) would never see event 10.
APPEND_LOCK_KEY = 7_000_001


@dataclass(frozen=True)
class NewEvent:
    """An event that has been decided but not stored yet."""

    event_type: str
    data: dict[str, Any]


@dataclass(frozen=True)
class StoredEvent:
    """An event as it sits in the store, with its position and version."""

    global_position: int
    stream_id: str
    stream_type: str
    version: int
    event_type: str
    data: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


def _to_stored(row: dict) -> StoredEvent:
    return StoredEvent(
        global_position=row["global_position"],
        stream_id=row["stream_id"],
        stream_type=row["stream_type"],
        version=row["version"],
        event_type=row["event_type"],
        data=row["data"],
        metadata=row["metadata"],
        occurred_at=row["occurred_at"],
    )


class EventStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def append(
        self,
        stream_id: str,
        stream_type: str,
        expected_version: int,
        events: list[NewEvent],
        metadata: dict[str, Any] | None = None,
    ) -> list[StoredEvent]:
        """Append events to a stream.

        expected_version is the version the caller saw when it loaded the stream
        (0 = "this stream must not exist yet"). If someone else appended in the
        meantime, ConcurrencyError is raised and nothing is written.
        """
        if not events:
            return []
        metadata = metadata or {}
        stored: list[StoredEvent] = []
        try:
            with self._pool.connection() as conn, conn.transaction():
                conn.execute("SELECT pg_advisory_xact_lock(%s)", (APPEND_LOCK_KEY,))
                current = self._current_version(conn, stream_id)
                if current != expected_version:
                    raise ConcurrencyError(
                        f"stream {stream_id} is at version {current}, expected {expected_version}"
                    )
                for offset, event in enumerate(events, start=1):
                    row = conn.execute(
                        """
                        INSERT INTO events (stream_id, stream_type, version, event_type, data, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING *
                        """,
                        (
                            stream_id,
                            stream_type,
                            expected_version + offset,
                            event.event_type,
                            json.dumps(event.data),
                            json.dumps(metadata),
                        ),
                    ).fetchone()
                    stored.append(_to_stored(row))
        except psycopg.errors.UniqueViolation as exc:
            # Backstop: the UNIQUE(stream_id, version) constraint caught a race.
            raise ConcurrencyError(f"stream {stream_id} was modified concurrently") from exc
        return stored

    def load_stream(self, stream_id: str, until: datetime | None = None) -> list[StoredEvent]:
        """All events of one stream in version order (optionally only up to a point in time)."""
        sql = "SELECT * FROM events WHERE stream_id = %s"
        params: list[Any] = [stream_id]
        if until is not None:
            sql += " AND occurred_at <= %s"
            params.append(until)
        sql += " ORDER BY version"
        with self._pool.connection() as conn:
            return [_to_stored(r) for r in conn.execute(sql, params).fetchall()]

    def read_all(
        self, after_position: int = 0, limit: int = 500, conn: Connection | None = None
    ) -> list[StoredEvent]:
        """Events from the global log after a position, oldest first."""
        sql = "SELECT * FROM events WHERE global_position > %s ORDER BY global_position LIMIT %s"
        if conn is not None:
            return [_to_stored(r) for r in conn.execute(sql, (after_position, limit)).fetchall()]
        with self._pool.connection() as c:
            return [_to_stored(r) for r in c.execute(sql, (after_position, limit)).fetchall()]

    def stream_version(self, stream_id: str) -> int:
        with self._pool.connection() as conn:
            return self._current_version(conn, stream_id)

    def head_position(self) -> int:
        """Position of the newest event in the store (0 when empty)."""
        with self._pool.connection() as conn:
            row = conn.execute("SELECT COALESCE(MAX(global_position), 0) AS head FROM events").fetchone()
            return row["head"]

    @staticmethod
    def _current_version(conn: Connection, stream_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM events WHERE stream_id = %s", (stream_id,)
        ).fetchone()
        return row["v"]
