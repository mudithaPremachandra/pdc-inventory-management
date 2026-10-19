
from typing import Any, TypeVar

from inventory.domain.aggregate import AggregateRoot
from inventory.domain.events import deserialize
from inventory.eventstore.store import EventStore, NewEvent, StoredEvent

A = TypeVar("A", bound=AggregateRoot)


class AggregateRepository:
    def __init__(self, store: EventStore):
        self.store = store

    def load(self, aggregate_cls: type[A], aggregate_id: str) -> A:
        """Replay the aggregate's stream. Returns an empty aggregate (version 0) if it has no events."""
        stream_id = f"{aggregate_cls.stream_type}-{aggregate_id}"
        history = [deserialize(e.event_type, e.data) for e in self.store.load_stream(stream_id)]
        return aggregate_cls.from_history(aggregate_id, history)

    def save(self, aggregate: AggregateRoot, metadata: dict[str, Any] | None = None) -> list[StoredEvent]:
        """Append the aggregate's pending events, expecting nobody else wrote since we loaded it."""
        new_events = [NewEvent(e.event_type, e.to_data()) for e in aggregate.pending_events]
        stored = self.store.append(
            stream_id=aggregate.stream_id,
            stream_type=aggregate.stream_type,
            expected_version=aggregate.version,
            events=new_events,
            metadata=metadata,
        )
        aggregate.version += len(stored)
        aggregate.pending_events.clear()
        return stored
