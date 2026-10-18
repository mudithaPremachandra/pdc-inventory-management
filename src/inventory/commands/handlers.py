import uuid
from dataclasses import dataclass
from typing import Callable, TypeVar

from inventory.commands.commands import (
    AdjustStock,
    DiscontinueProduct,
    DispatchStock,
    ReceiveStock,
    RegisterProduct,
    UpdateProductDetails,
)
from inventory.domain.aggregate import AggregateRoot
from inventory.domain.errors import ConcurrencyError
from inventory.domain.product import Product, normalise_sku
from inventory.eventstore.repository import AggregateRepository

A = TypeVar("A", bound=AggregateRoot)

MAX_ATTEMPTS = 3


@dataclass(frozen=True)
class CommandResult:
    stream_id: str
    version: int
    # Position of the last appended event. The CLI waits until the projector's
    # checkpoint reaches it, so a query right after a command sees the change.
    global_position: int
    events: list[str]


class CommandHandler:
    def __init__(self, repository: AggregateRepository):
        self.repository = repository
        self._routes: dict[type, Callable] = {
            RegisterProduct: self._register_product,
            UpdateProductDetails: self._update_product,
            ReceiveStock: self._receive_stock,
            DispatchStock: self._dispatch_stock,
            AdjustStock: self._adjust_stock,
            DiscontinueProduct: self._discontinue_product,
        }

    def handle(self, command, username: str) -> CommandResult:
        """Command bus: route a command object to its handler."""
        try:
            handler = self._routes[type(command)]
        except KeyError as exc:
            raise TypeError(f"no handler for {type(command).__name__}") from exc
        return handler(command, username)

    def execute(
        self,
        aggregate_cls: type[A],
        aggregate_id: str,
        decide: Callable[[A], None],
        username: str,
        command_name: str,
    ) -> CommandResult:
        """Load -> decide -> append, retrying on optimistic-concurrency conflicts."""
        metadata = {"user": username, "command": command_name, "correlation_id": str(uuid.uuid4())}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            aggregate = self.repository.load(aggregate_cls, aggregate_id)
            decide(aggregate)
            try:
                stored = self.repository.save(aggregate, metadata)
            except ConcurrencyError:
                if attempt == MAX_ATTEMPTS:
                    raise
                continue
            return CommandResult(
                stream_id=aggregate.stream_id,
                version=aggregate.version,
                global_position=stored[-1].global_position,
                events=[e.event_type for e in stored],
            )
        raise AssertionError("unreachable")

    # --- one small method per command --------------------------------------------

    def _register_product(self, c: RegisterProduct, username: str) -> CommandResult:
        return self.execute(
            Product, normalise_sku(c.sku),
            lambda p: p.register(c.name, c.unit_price, c.reorder_level, c.category),
            username, "RegisterProduct",
        )

    def _update_product(self, c: UpdateProductDetails, username: str) -> CommandResult:
        return self.execute(
            Product, normalise_sku(c.sku),
            lambda p: p.update_details(c.name, c.category, c.unit_price, c.reorder_level),
            username, "UpdateProductDetails",
        )

    def _receive_stock(self, c: ReceiveStock, username: str) -> CommandResult:
        return self.execute(
            Product, normalise_sku(c.sku),
            lambda p: p.receive(c.quantity, c.reference),
            username, "ReceiveStock",
        )

    def _dispatch_stock(self, c: DispatchStock, username: str) -> CommandResult:
        return self.execute(
            Product, normalise_sku(c.sku),
            lambda p: p.dispatch(c.quantity, c.reference),
            username, "DispatchStock",
        )

    def _adjust_stock(self, c: AdjustStock, username: str) -> CommandResult:
        return self.execute(
            Product, normalise_sku(c.sku),
            lambda p: p.adjust(c.quantity_change, c.reason),
            username, "AdjustStock",
        )

    def _discontinue_product(self, c: DiscontinueProduct, username: str) -> CommandResult:
        return self.execute(
            Product, normalise_sku(c.sku),
            lambda p: p.discontinue(c.reason),
            username, "DiscontinueProduct",
        )
