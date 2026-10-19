import json
from decimal import Decimal

import pytest

from inventory.auth.user import UserRegistered
from inventory.domain.events import (
    EVENT_REGISTRY,
    ProductDetailsUpdated,
    ProductRegistered,
    StockAdjusted,
    StockReceived,
    deserialize,
)


@pytest.mark.parametrize("event", [
    ProductRegistered("A1", "Widget", None, Decimal("10.50"), 3),
    ProductDetailsUpdated("A1", unit_price=Decimal("2.00")),
    ProductDetailsUpdated("A1", name="New"),
    StockReceived("A1", 7, "PO-1"),
    StockAdjusted("A1", -2, "broken"),
    UserRegistered("kasun", "clerk", "$2b$hash"),
])
def test_round_trip_through_json(event):
    stored = json.loads(json.dumps(event.to_data()))
    assert deserialize(event.event_type, stored) == event


def test_decimal_is_stored_as_string_not_float():
    data = ProductRegistered("A1", "Widget", None, Decimal("0.10"), 0).to_data()
    assert data["unit_price"] == "0.10"


def test_event_type_is_the_class_name():
    assert StockReceived.event_type == "StockReceived"


def test_all_product_and_user_events_are_registered():
    for name in ["ProductRegistered", "ProductDetailsUpdated", "StockReceived", "StockDispatched",
                 "StockAdjusted", "ProductDiscontinued", "UserRegistered", "UserRoleChanged",
                 "UserPasswordChanged", "UserDeactivated", "UserReactivated"]:
        assert name in EVENT_REGISTRY


def test_unknown_event_type_is_an_error():
    with pytest.raises(ValueError):
        deserialize("SomethingElse", {})


def test_events_are_immutable():
    event = StockReceived("A1", 7)
    with pytest.raises(Exception):
        event.quantity = 8
