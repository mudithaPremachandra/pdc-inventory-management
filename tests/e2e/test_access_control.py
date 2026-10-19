"""Authentication and role-based access control across both APIs."""

import pytest

NEW_PRODUCT = {"sku": "AC-1", "name": "Thing", "unit_price": "1.00", "reorder_level": 0}


def test_requests_without_login_are_rejected(command_api, query_api):
    assert command_api.post("/products", json=NEW_PRODUCT).status_code == 401
    assert query_api.get("/products").status_code == 401


def test_wrong_password_and_unknown_user_look_the_same(command_api):
    a = command_api.post("/auth/login", json={"username": "admin", "password": "nope"})
    b = command_api.post("/auth/login", json={"username": "ghost", "password": "nope"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


@pytest.mark.parametrize("role, method, path, body, allowed", [
    ("viewer", "post", "/products", NEW_PRODUCT, False),
    ("clerk", "post", "/products", NEW_PRODUCT, False),
    ("manager", "post", "/products", NEW_PRODUCT, True),
    ("clerk", "post", "/users", {"username": "zed", "password": "password1", "role": "viewer"}, False),
    ("manager", "post", "/users", {"username": "zed", "password": "password1", "role": "viewer"}, False),
])
def test_command_permissions(command_api, user_with_role, role, method, path, body, allowed):
    headers = user_with_role(role)
    status = getattr(command_api, method)(path, headers=headers, json=body).status_code
    assert (status == 202) is allowed and (status == 403) is (not allowed)


def test_clerk_can_move_stock_but_not_adjust(command_api, admin, user_with_role):
    command_api.post("/products", headers=admin, json=NEW_PRODUCT)
    clerk = user_with_role("clerk")
    assert command_api.post("/products/AC-1/receive", headers=clerk, json={"quantity": 5}).status_code == 202
    assert command_api.post("/products/AC-1/adjust", headers=clerk,
                            json={"quantity_change": -1, "reason": "x"}).status_code == 403


def test_viewer_can_read_but_not_see_users_or_events(query_api, user_with_role):
    viewer = user_with_role("viewer")
    assert query_api.get("/products", headers=viewer).status_code == 200
    assert query_api.get("/users", headers=viewer).status_code == 403
    assert query_api.get("/events", headers=viewer).status_code == 403


def test_deactivation_blocks_an_existing_token_immediately(command_api, query_api, admin, user_with_role):
    clerk = user_with_role("clerk")  # username clerk1
    assert query_api.get("/products", headers=clerk).status_code == 200
    assert command_api.post("/users/clerk1/deactivate", headers=admin).status_code == 202
    assert query_api.get("/products", headers=clerk).status_code == 401
    assert command_api.post("/auth/login", json={"username": "clerk1", "password": "password1"}).status_code == 401


def test_role_change_applies_without_logging_in_again(command_api, admin, user_with_role):
    viewer = user_with_role("viewer")  # username viewer1
    assert command_api.post("/products", headers=viewer, json=NEW_PRODUCT).status_code == 403
    command_api.post("/users/viewer1/role", headers=admin, json={"role": "manager"})
    assert command_api.post("/products", headers=viewer, json=NEW_PRODUCT).status_code == 202


def test_admin_cannot_lock_themselves_out(command_api, admin):
    assert command_api.post("/users/admin/deactivate", headers=admin).status_code == 400
    assert command_api.post("/users/admin/role", headers=admin, json={"role": "viewer"}).status_code == 400


def test_change_own_password(command_api, user_with_role):
    clerk = user_with_role("clerk")
    r = command_api.post("/auth/password", headers=clerk, json={"old_password": "password1", "new_password": "newpass99"})
    assert r.status_code == 202
    assert command_api.post("/auth/login", json={"username": "clerk1", "password": "newpass99"}).status_code == 200

