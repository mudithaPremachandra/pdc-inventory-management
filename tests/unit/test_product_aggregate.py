from decimal import Decimal

import pytest

from inventory.domain.errors import AlreadyExists, DomainError, InsufficientStock, InvalidInput, NotFound
from inventory.domain.events import (
    ProductDetailsUpdated,
    ProductDiscontinued,
    ProductRegistered,
    StockAdjusted,
    StockDispatched,
    StockReceived,
)
from inventory.domain.product import Product, normalise_sku

SKU = "CBL-001"
REGISTERED = ProductRegistered(sku=SKU, name="USB-C cable", category="cables",
                               unit_price=Decimal("4.99"), reorder_level=10)


def given(*history) -> Product:
    return Product.from_history(SKU, history)


def when(product: Product, action) -> list:
    action(product)
    return product.pending_events


# --- registering ---------------------------------------------------------------------


def test_register_new_product_records_product_registered():
    events = when(given(), lambda p: p.register("USB-C cable", "4.99", 10, "cables"))
    assert events == [REGISTERED]


def test_register_rounds_price_to_cents_and_trims_text():
    events = when(given(), lambda p: p.register("  Cable  ", "4.5", 0, "  "))
    assert events[0].unit_price == Decimal("4.50")
    assert events[0].name == "Cable"
    assert events[0].category is None


def test_cannot_register_the_same_sku_twice():
    with pytest.raises(AlreadyExists):
        when(given(REGISTERED), lambda p: p.register("Other", "1", 1))


@pytest.mark.parametrize("name, price, reorder", [
    ("", "1.00", 1),         # empty name
    ("Cable", "-1", 1),      # negative price
    ("Cable", "abc", 1),     # not a number
    ("Cable", "1.00", -5),   # negative reorder level
])
def test_register_rejects_invalid_input(name, price, reorder):
    with pytest.raises(InvalidInput):
        when(given(), lambda p: p.register(name, price, reorder))


@pytest.mark.parametrize("raw, expected", [("cbl-001", "CBL-001"), (" ab ", "AB"), ("X_1", "X_1")])
def test_sku_is_normalised(raw, expected):
    assert normalise_sku(raw) == expected


@pytest.mark.parametrize("raw", ["", "a", "has space", "-START", "x" * 40])
def test_invalid_sku_is_rejected(raw):
    with pytest.raises(InvalidInput):
        normalise_sku(raw)


# --- receiving and dispatching ---------------------------------------------------------


def test_receive_records_stock_received():
    events = when(given(REGISTERED), lambda p: p.receive(50, "PO-1"))
    assert events == [StockReceived(sku=SKU, quantity=50, reference="PO-1")]


def test_cannot_receive_for_unknown_product():
    with pytest.raises(NotFound):
        when(given(), lambda p: p.receive(5))


@pytest.mark.parametrize("qty", [0, -3])
def test_receive_needs_positive_quantity(qty):
    with pytest.raises(InvalidInput):
        when(given(REGISTERED), lambda p: p.receive(qty))


def test_dispatch_within_stock_records_stock_dispatched():
    events = when(given(REGISTERED, StockReceived(SKU, 10)), lambda p: p.dispatch(4, "SO-9"))
    assert events == [StockDispatched(sku=SKU, quantity=4, reference="SO-9")]


def test_dispatch_more_than_in_stock_is_refused():
    with pytest.raises(InsufficientStock):
        when(given(REGISTERED, StockReceived(SKU, 10), StockDispatched(SKU, 8)), lambda p: p.dispatch(3))


def test_dispatch_exactly_all_stock_is_allowed():
    product = given(REGISTERED, StockReceived(SKU, 10))
    when(product, lambda p: p.dispatch(10))
    assert product.quantity_on_hand == 0


# --- adjusting ---------------------------------------------------------------------


def test_adjust_down_with_reason():
    events = when(given(REGISTERED, StockReceived(SKU, 10)), lambda p: p.adjust(-2, "damaged"))
    assert events == [StockAdjusted(sku=SKU, quantity_change=-2, reason="damaged")]


def test_adjust_needs_a_reason_and_non_zero_change():
    product = given(REGISTERED, StockReceived(SKU, 10))
    with pytest.raises(InvalidInput):
        product.adjust(-1, "  ")
    with pytest.raises(InvalidInput):
        product.adjust(0, "count")


def test_adjust_cannot_make_stock_negative():
    with pytest.raises(InsufficientStock):
        when(given(REGISTERED, StockReceived(SKU, 3)), lambda p: p.adjust(-4, "lost"))


def test_adjust_is_allowed_on_discontinued_product_to_write_off_stock():
    events = when(given(REGISTERED, StockReceived(SKU, 3), ProductDiscontinued(SKU)), lambda p: p.adjust(-3, "write-off"))
    assert events[0].quantity_change == -3


# --- details and discontinuing -------------------------------------------------------------


def test_update_records_only_changed_fields():
    events = when(given(REGISTERED), lambda p: p.update_details(name="USB-C cable", unit_price="5.49"))
    assert events == [ProductDetailsUpdated(sku=SKU, unit_price=Decimal("5.49"))]


def test_update_with_no_changes_is_refused():
    with pytest.raises(DomainError):
        when(given(REGISTERED), lambda p: p.update_details(name="USB-C cable"))


def test_discontinued_product_refuses_stock_movements_and_updates():
    product = given(REGISTERED, StockReceived(SKU, 5), ProductDiscontinued(SKU, "old"))
    for action in (lambda p: p.receive(1), lambda p: p.dispatch(1), lambda p: p.update_details(name="x"),
                   lambda p: p.discontinue()):
        with pytest.raises(DomainError):
            action(product)


# --- replay -------------------------------------------------------------------------


def test_state_is_rebuilt_by_replaying_history():
    product = given(
        REGISTERED,
        StockReceived(SKU, 50),
        StockDispatched(SKU, 20),
        StockAdjusted(SKU, -5, "count"),
        ProductDetailsUpdated(SKU, unit_price=Decimal("6.00")),
    )
    assert product.quantity_on_hand == 25
    assert product.unit_price == Decimal("6.00")
    assert product.version == 5
    assert product.pending_events == []


def test_new_events_bump_state_but_not_stored_version():
    product = given(REGISTERED)
    product.receive(5)
    assert product.quantity_on_hand == 5
    assert product.version == 1  # only the repository moves the version, after the append succeeds

