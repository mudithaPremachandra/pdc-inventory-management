import dataclasses
import typing
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, ClassVar

EVENT_REGISTRY: dict[str, type["DomainEvent"]] = {}


def register_event(cls):
    """Class decorator: make an event type known to deserialize()."""
    EVENT_REGISTRY[cls.__name__] = cls
    return cls


@dataclass(frozen=True)
class DomainEvent:
    event_type: ClassVar[str]

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls.event_type = cls.__name__

    def to_data(self) -> dict[str, Any]:
        """Turn the event into JSON-safe data (Decimal -> str)."""
        return {
            k: (str(v) if isinstance(v, Decimal) else v) for k, v in dataclasses.asdict(self).items()
        }

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> "DomainEvent":
        hints = typing.get_type_hints(cls)
        values = {}
        for f in dataclasses.fields(cls):
            value = data.get(f.name)
            hint = hints[f.name]
            if value is not None and (hint is Decimal or Decimal in typing.get_args(hint)):
                value = Decimal(value)
            values[f.name] = value
        return cls(**values)


def deserialize(event_type: str, data: dict[str, Any]) -> DomainEvent:
    try:
        cls = EVENT_REGISTRY[event_type]
    except KeyError as exc:
        raise ValueError(f"unknown event type {event_type!r}") from exc
    return cls.from_data(data)


# --- Product events ---------------------------------------------------------


@register_event
@dataclass(frozen=True)
class ProductRegistered(DomainEvent):
    sku: str
    name: str
    category: str | None
    unit_price: Decimal
    reorder_level: int


@register_event
@dataclass(frozen=True)
class ProductDetailsUpdated(DomainEvent):
    """Only the fields that changed are set; the rest are None."""

    sku: str
    name: str | None = None
    category: str | None = None
    unit_price: Decimal | None = None
    reorder_level: int | None = None


@register_event
@dataclass(frozen=True)
class StockReceived(DomainEvent):
    sku: str
    quantity: int
    reference: str | None = None


@register_event
@dataclass(frozen=True)
class StockDispatched(DomainEvent):
    sku: str
    quantity: int
    reference: str | None = None


@register_event
@dataclass(frozen=True)
class StockAdjusted(DomainEvent):
    """Correction after a stock count, damage, theft... quantity_change can be + or -."""

    sku: str
    quantity_change: int
    reason: str


@register_event
@dataclass(frozen=True)
class ProductDiscontinued(DomainEvent):
    sku: str
    reason: str | None = None

