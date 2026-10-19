"""Projector and rebuild: the read models must always match the events."""

from inventory.commands.commands import (
    AdjustStock,
    DiscontinueProduct,
    DispatchStock,
    ReceiveStock,
    RegisterProduct,
    UpdateProductDetails,
)
from inventory.projections.projector import PROJECTION_NAME
from inventory.projections.rebuild import rebuild
from inventory.queries import queries


def _seed(handler):
    handler.handle(RegisterProduct("A-1", "Alpha", "2.50", 10, "tools"), "alice")
    handler.handle(RegisterProduct("B-1", "Beta", "1.00", 0, "parts"), "alice")
    handler.handle(ReceiveStock("A-1", 30, "PO-1"), "bob")
    handler.handle(DispatchStock("A-1", 25, "SO-1"), "bob")
    handler.handle(AdjustStock("A-1", -1, "broken"), "alice")
    handler.handle(UpdateProductDetails("B-1", unit_price="1.20"), "alice")
    handler.handle(DiscontinueProduct("B-1", "old"), "alice")


def _snapshot(pool):
    with pool.connection() as conn:
        products = conn.execute("SELECT sku, quantity, unit_price, status, version FROM read.products ORDER BY sku").fetchall()
        movements = conn.execute("SELECT * FROM read.stock_movements ORDER BY global_position").fetchall()
    return products, movements


def test_read_model_is_empty_until_the_projector_runs(handler, clean_db, project):
    _seed(handler)
    assert queries.list_products(clean_db) == []          # eventual consistency: not there yet
    assert queries.projection_status(clean_db)["lag"] == 7
    project()
    assert queries.projection_status(clean_db)["lag"] == 0
    assert [p["sku"] for p in queries.list_products(clean_db, include_discontinued=True)] == ["A-1", "B-1"]


def test_projected_state_matches_the_events(handler, clean_db, project):
    _seed(handler)
    project()
    a1 = queries.get_product(clean_db, "A-1")
    assert a1["quantity"] == 4 and a1["version"] == 4
    b1 = queries.get_product(clean_db, "B-1")
    assert str(b1["unit_price"]) == "1.20" and b1["status"] == "discontinued"
    history = queries.stock_history(clean_db, "A-1")
    assert [(m["movement_type"], m["quantity_change"], m["quantity_after"]) for m in history] == [
        ("received", 30, 30), ("dispatched", -25, 5), ("adjusted", -1, 4),
    ]
    assert history[0]["performed_by"] == "bob"
    assert [r["sku"] for r in queries.low_stock(clean_db)] == ["A-1"]


def test_replaying_the_same_events_twice_changes_nothing(handler, clean_db, project):
    """Idempotency: if the projector crashes before saving its checkpoint, events are re-applied."""
    _seed(handler)
    project()
    before = _snapshot(clean_db)
    with clean_db.connection() as conn:
        conn.execute("UPDATE read.projection_checkpoints SET last_position = 0 WHERE projection_name = %s",
                     (PROJECTION_NAME,))
    project()
    assert _snapshot(clean_db) == before


def test_rebuild_reproduces_the_live_read_model(handler, clean_db, project):
    _seed(handler)
    project()
    before = _snapshot(clean_db)
    with clean_db.connection() as conn:  # simulate a corrupted read model
        conn.execute("UPDATE read.products SET quantity = 999")
    result = rebuild(clean_db)
    assert result["replayed_events"] == 7
    assert _snapshot(clean_db) == before
