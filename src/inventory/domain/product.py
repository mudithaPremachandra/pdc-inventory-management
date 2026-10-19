import re
from decimal import Decimal, InvalidOperation

from inventory.domain.aggregate import AggregateRoot
from inventory.domain.errors import AlreadyExists, DomainError, InsufficientStock, InvalidInput, NotFound
from inventory.domain.events import (
    ProductDetailsUpdated,
    ProductDiscontinued,
    ProductRegistered,
    StockAdjusted,
    StockDispatched,
    StockReceived,
)

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}$")


def normalise_sku(sku: str) -> str:
    sku = (sku or "").strip().upper()
    if not SKU_PATTERN.match(sku):
        raise InvalidInput("SKU must be 2-32 characters: letters, digits, '-' or '_'")
    return sku


def _price(value) -> Decimal:
    try:
        price = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise InvalidInput(f"invalid price {value!r}") from exc
    if price < 0:
        raise InvalidInput("price cannot be negative")
    return price


def _reorder_level(value) -> int:
    if not isinstance(value, int) or value < 0:
        raise InvalidInput("reorder level must be a whole number >= 0")
    return value


def _positive_quantity(quantity) -> int:
    if not isinstance(quantity, int) or quantity <= 0:
        raise InvalidInput("quantity must be a whole number greater than 0")
    return quantity


def _name(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise InvalidInput("name cannot be empty")
    return value


class Product(AggregateRoot):
    stream_type = "product"

    def __init__(self, sku: str):
        super().__init__(sku)
        self.name: str = ""
        self.category: str | None = None
        self.unit_price = Decimal("0")
        self.reorder_level = 0
        self.quantity_on_hand = 0
        self.discontinued = False

    # --- commands: check rules, then record events ---------------------------

    def register(self, name: str, unit_price, reorder_level: int, category: str | None = None) -> None:
        if self.exists:
            raise AlreadyExists(f"product {self.id} already exists")
        self._record(
            ProductRegistered(
                sku=self.id,
                name=_name(name),
                category=(category or "").strip() or None,
                unit_price=_price(unit_price),
                reorder_level=_reorder_level(reorder_level),
            )
        )

    def update_details(self, name=None, category=None, unit_price=None, reorder_level=None) -> None:
        self._ensure_active()
        changes = {}
        if name is not None and _name(name) != self.name:
            changes["name"] = _name(name)
        if category is not None and category.strip() and category.strip() != self.category:
            changes["category"] = category.strip()
        if unit_price is not None and _price(unit_price) != self.unit_price:
            changes["unit_price"] = _price(unit_price)
        if reorder_level is not None and _reorder_level(reorder_level) != self.reorder_level:
            changes["reorder_level"] = reorder_level
        if not changes:
            raise DomainError("nothing to update: the new values are the same as the current ones")
        self._record(ProductDetailsUpdated(sku=self.id, **changes))

    def receive(self, quantity: int, reference: str | None = None) -> None:
        self._ensure_active()
        self._record(StockReceived(sku=self.id, quantity=_positive_quantity(quantity), reference=reference))

    def dispatch(self, quantity: int, reference: str | None = None) -> None:
        self._ensure_active()
        quantity = _positive_quantity(quantity)
        if quantity > self.quantity_on_hand:
            raise InsufficientStock(
                f"cannot dispatch {quantity} of {self.id}: only {self.quantity_on_hand} in stock"
            )
        self._record(StockDispatched(sku=self.id, quantity=quantity, reference=reference))

    def adjust(self, quantity_change: int, reason: str) -> None:
        # Allowed on discontinued products too, so leftover stock can be written off.
        self._ensure_exists()
        if not isinstance(quantity_change, int) or quantity_change == 0:
            raise InvalidInput("adjustment must be a non-zero whole number")
        if not (reason or "").strip():
            raise InvalidInput("a reason is required for stock adjustments")
        if self.quantity_on_hand + quantity_change < 0:
            raise InsufficientStock(
                f"adjustment of {quantity_change} would leave {self.id} with negative stock "
                f"(currently {self.quantity_on_hand})"
            )
        self._record(StockAdjusted(sku=self.id, quantity_change=quantity_change, reason=reason.strip()))

    def discontinue(self, reason: str | None = None) -> None:
        self._ensure_active()
        self._record(ProductDiscontinued(sku=self.id, reason=reason))

    def _ensure_exists(self) -> None:
        if not self.exists:
            raise NotFound(f"product {self.id} does not exist")

    def _ensure_active(self) -> None:
        self._ensure_exists()
        if self.discontinued:
            raise DomainError(f"product {self.id} is discontinued")

    # --- event appliers: change state, never fail ------------------------------

    def on_ProductRegistered(self, e: ProductRegistered) -> None:
        self.name = e.name
        self.category = e.category
        self.unit_price = e.unit_price
        self.reorder_level = e.reorder_level

    def on_ProductDetailsUpdated(self, e: ProductDetailsUpdated) -> None:
        if e.name is not None:
            self.name = e.name
        if e.category is not None:
            self.category = e.category
        if e.unit_price is not None:
            self.unit_price = e.unit_price
        if e.reorder_level is not None:
            self.reorder_level = e.reorder_level

    def on_StockReceived(self, e: StockReceived) -> None:
        self.quantity_on_hand += e.quantity

    def on_StockDispatched(self, e: StockDispatched) -> None:
        self.quantity_on_hand -= e.quantity

    def on_StockAdjusted(self, e: StockAdjusted) -> None:
        self.quantity_on_hand += e.quantity_change

    def on_ProductDiscontinued(self, e: ProductDiscontinued) -> None:
        self.discontinued = True

    def snapshot(self) -> dict:
        """Plain-dict view of the current state (used by time-travel queries)."""
        return {
            "sku": self.id,
            "name": self.name,
            "category": self.category,
            "unit_price": str(self.unit_price),
            "reorder_level": self.reorder_level,
            "quantity": self.quantity_on_hand,
            "status": "discontinued" if self.discontinued else "active",
            "version": self.version,
        }
