import pytest

from inventory.auth.passwords import hash_password, verify_password
from inventory.auth.permissions import ROLE_PERMISSIONS, Perm, has_permission
from inventory.auth.tokens import InvalidToken, issue_token, verify_token
from inventory.auth.user import User, UserDeactivated, UserRegistered, UserRoleChanged, normalise_username
from inventory.domain.errors import AlreadyExists, DomainError, InvalidInput, NotFound

REGISTERED = UserRegistered(username="nimal", role="clerk", password_hash="h")


def given(*history) -> User:
    return User.from_history("nimal", history)


# --- User aggregate ---------------------------------------------------------------------


def test_register_user():
    user = given()
    user.register("clerk", "h")
    assert user.pending_events == [REGISTERED]
    assert user.active and user.role == "clerk"


def test_register_rejects_unknown_role():
    with pytest.raises(InvalidInput):
        given().register("superuser", "h")


def test_username_must_be_unique():
    with pytest.raises(AlreadyExists):
        given(REGISTERED).register("viewer", "h")


def test_change_role_records_old_and_new_role():
    user = given(REGISTERED)
    user.change_role("manager")
    assert user.pending_events == [UserRoleChanged("nimal", "clerk", "manager")]


def test_change_to_same_role_is_refused():
    with pytest.raises(DomainError):
        given(REGISTERED).change_role("clerk")


def test_deactivate_and_reactivate():
    user = given(REGISTERED)
    user.deactivate()
    assert not user.active
    with pytest.raises(DomainError):
        user.deactivate()
    user.reactivate()
    assert user.active


def test_actions_on_missing_user_raise_not_found():
    with pytest.raises(NotFound):
        given().deactivate()


def test_replay_gives_latest_role_and_status():
    user = given(REGISTERED, UserRoleChanged("nimal", "clerk", "manager"), UserDeactivated("nimal"))
    assert (user.role, user.active, user.version) == ("manager", False, 3)


@pytest.mark.parametrize("raw, ok", [("Nimal", "nimal"), ("a.b-c_1", "a.b-c_1")])
def test_username_normalised(raw, ok):
    assert normalise_username(raw) == ok


@pytest.mark.parametrize("raw", ["ab", "1abc", "has space", ""])
def test_bad_usernames(raw):
    with pytest.raises(InvalidInput):
        normalise_username(raw)


# --- passwords and tokens ---------------------------------------------------------------


def test_password_hash_verifies_and_is_salted():
    h1, h2 = hash_password("secret1"), hash_password("secret1")
    assert h1 != h2 and "secret1" not in h1
    assert verify_password("secret1", h1)
    assert not verify_password("wrong", h1)


def test_short_password_rejected():
    with pytest.raises(InvalidInput):
        hash_password("123")


def test_token_round_trip():
    claims = verify_token(issue_token("nimal", "clerk"))
    assert claims["sub"] == "nimal" and claims["role"] == "clerk"


def test_tampered_token_rejected():
    token = issue_token("nimal", "clerk")
    with pytest.raises(InvalidToken):
        verify_token(token[:-2] + ("aa" if not token.endswith("aa") else "bb"))


# --- RBAC matrix ------------------------------------------------------------------------


def test_admin_has_every_permission():
    assert all(has_permission("admin", p) for p in ROLE_PERMISSIONS["admin"])
    assert has_permission("admin", Perm.USERS_MANAGE)


@pytest.mark.parametrize("role, perm, allowed", [
    ("manager", Perm.PRODUCT_MANAGE, True),
    ("manager", Perm.USERS_MANAGE, False),
    ("clerk", Perm.STOCK_RECEIVE, True),
    ("clerk", Perm.STOCK_ADJUST, False),
    ("clerk", Perm.PRODUCT_MANAGE, False),
    ("viewer", Perm.INVENTORY_READ, True),
    ("viewer", Perm.STOCK_DISPATCH, False),
    ("nobody", Perm.INVENTORY_READ, False),
])
def test_role_permissions(role, perm, allowed):
    assert has_permission(role, perm) is allowed

