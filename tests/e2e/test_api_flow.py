"""Full flow through both HTTP APIs: commands to the write side, queries to the read side."""


def test_full_inventory_flow(command_api, query_api, admin, project):
    # Write side: commands come back 202 with what was appended.
    r = command_api.post("/products", headers=admin, json={
        "sku": "kb-01", "name": "Keyboard", "unit_price": "25.00", "reorder_level": 5, "category": "peripherals"})
    assert r.status_code == 202
    assert r.json()["stream_id"] == "product-KB-01" and r.json()["events"] == ["ProductRegistered"]

    assert command_api.post("/products/KB-01/receive", headers=admin, json={"quantity": 10}).status_code == 202
    too_many = command_api.post("/products/KB-01/dispatch", headers=admin, json={"quantity": 11})
    assert too_many.status_code == 409 and "only 10 in stock" in too_many.json()["detail"]
    r = command_api.post("/products/KB-01/dispatch", headers=admin, json={"quantity": 7, "reference": "SO-1"})
    assert r.json()["version"] == 3

    # Read side: catches up once the projector has run.
    project()
    product = query_api.get("/products/KB-01", headers=admin).json()
    assert product["quantity"] == 3
    assert [m["quantity_change"] for m in query_api.get("/products/KB-01/history", headers=admin).json()] == [10, -7]
    assert query_api.get("/reports/low-stock", headers=admin).json()[0]["sku"] == "KB-01"
    assert float(query_api.get("/reports/valuation", headers=admin).json()["total_value"]) == 75.0
    assert query_api.get("/status", headers=admin).json()["lag"] == 0


def test_time_travel_replays_events_up_to_a_moment(command_api, query_api, admin):
    command_api.post("/products", headers=admin, json={"sku": "TT-1", "name": "T", "unit_price": "1", "reorder_level": 0})
    command_api.post("/products/TT-1/receive", headers=admin, json={"quantity": 50})
    command_api.post("/products/TT-1/dispatch", headers=admin, json={"quantity": 20})

    log = query_api.get("/events", headers=admin, params={"stream": "product-TT-1"}).json()
    registered_at, received_at, dispatched_at = (e["occurred_at"] for e in log)

    def qty_at(moment):
        return query_api.get("/products/TT-1/as-of", headers=admin, params={"at": moment}).json()["quantity"]

    assert qty_at(registered_at) == 0
    assert qty_at(received_at) == 50
    assert qty_at(dispatched_at) == 30
    assert query_api.get("/products/TT-1/as-of", headers=admin,
                         params={"at": "2000-01-01T00:00:00Z"}).status_code == 404


def test_event_log_hides_password_hashes(query_api, admin):
    log = query_api.get("/events", headers=admin, params={"stream": "user-admin"}).json()
    assert log[0]["event_type"] == "UserRegistered"
    assert log[0]["data"]["password_hash"] == "***"


def test_rebuild_endpoint(command_api, query_api, admin, project):
    command_api.post("/products", headers=admin, json={"sku": "RB-1", "name": "R", "unit_price": "1", "reorder_level": 0})
    project()
    result = query_api.post("/admin/rebuild-projections", headers=admin).json()
    assert result["replayed_events"] == 2  # admin seeded + product registered
    assert query_api.get("/products/RB-1", headers=admin).status_code == 200


def test_validation_errors_are_reported(command_api, admin):
    r = command_api.post("/products", headers=admin, json={"sku": "x y", "name": "Bad", "unit_price": "1", "reorder_level": 0})
    assert r.status_code == 422
    r = command_api.post("/products/NOPE-1/receive", headers=admin, json={"quantity": 1})
    assert r.status_code == 404
    command_api.post("/products", headers=admin, json={"sku": "DUP-1", "name": "D", "unit_price": "1", "reorder_level": 0})
    r = command_api.post("/products", headers=admin, json={"sku": "dup-1", "name": "D", "unit_price": "1", "reorder_level": 0})
    assert r.status_code == 409
