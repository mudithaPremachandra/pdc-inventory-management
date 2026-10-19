from typing import ClassVar, Iterable

from inventory.domain.events import DomainEvent


class AggregateRoot:
    stream_type: ClassVar[str]

    def __init__(self, aggregate_id: str):
        self.id = aggregate_id
        # Number of events already in the store for this aggregate.
        self.version = 0
        self.pending_events: list[DomainEvent] = []

    @property
    def stream_id(self) -> str:
        return f"{self.stream_type}-{self.id}"

    @property
    def exists(self) -> bool:
        return self.version > 0 or bool(self.pending_events)

    @classmethod
    def from_history(cls, aggregate_id: str, history: Iterable[DomainEvent]):
        """Rebuild an aggregate by replaying the events it produced in the past."""
        aggregate = cls(aggregate_id)
        for event in history:
            aggregate._apply(event)
            aggregate.version += 1
        return aggregate

    def _record(self, event: DomainEvent) -> None:
        """Accept a new event: change state now, store it later."""
        self._apply(event)
        self.pending_events.append(event)

    def _apply(self, event: DomainEvent) -> None:
        # Dispatch to e.g. `on_StockReceived(self, event)`.
        handler = getattr(self, f"on_{event.event_type}", None)
        if handler is None:
            raise NotImplementedError(f"{type(self).__name__} cannot apply {event.event_type}")
        handler(event)