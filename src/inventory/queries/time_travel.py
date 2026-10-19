
from datetime import datetime, timezone

from inventory.domain.errors import NotFound
from inventory.domain.events import deserialize
from inventory.domain.product import Product, normalise_sku
from inventory.eventstore.store import EventStore


def product_as_of(store: EventStore, sku: str, at: datetime) -> dict:
    sku = normalise_sku(sku)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    stored = store.load_stream(f"{Product.stream_type}-{sku}", until=at)
    if not stored:
        raise NotFound(f"product {sku} did not exist at {at.isoformat()}")
    product = Product.from_history(sku, [deserialize(e.event_type, e.data) for e in stored])
    return {
        **product.snapshot(),
        "as_of": at.isoformat(),
        "events_replayed": len(stored),
        "last_event_at": stored[-1].occurred_at.isoformat(),
    }
