from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RegisterProduct:
    sku: str
    name: str
    unit_price: Decimal
    reorder_level: int
    category: str | None = None


@dataclass(frozen=True)
class UpdateProductDetails:
    sku: str
    name: str | None = None
    category: str | None = None
    unit_price: Decimal | None = None
    reorder_level: int | None = None


@dataclass(frozen=True)
class ReceiveStock:
    sku: str
    quantity: int
    reference: str | None = None


@dataclass(frozen=True)
class DispatchStock:
    sku: str
    quantity: int
    reference: str | None = None


@dataclass(frozen=True)
class AdjustStock:
    sku: str
    quantity_change: int
    reason: str


@dataclass(frozen=True)
class DiscontinueProduct:
    sku: str
    reason: str | None = None
