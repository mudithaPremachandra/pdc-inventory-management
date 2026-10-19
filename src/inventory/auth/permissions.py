

"""Role-based access control (RBAC).

Endpoints ask for a *permission*, never a role. The matrix below maps roles to
permissions, so adding a role never means touching endpoint code.
"""

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from inventory.auth.tokens import InvalidToken, verify_token
from inventory.db import get_pool
from inventory.eventstore.repository import AggregateRepository
from inventory.eventstore.store import EventStore


class Perm:
    PRODUCT_MANAGE = "product:manage"
    STOCK_RECEIVE = "stock:receive"
    STOCK_DISPATCH = "stock:dispatch"
    STOCK_ADJUST = "stock:adjust"
    INVENTORY_READ = "inventory:read"
    REPORTS_READ = "reports:read"
    EVENTS_READ = "events:read"
    USERS_MANAGE = "users:manage"
    PROJECTIONS_REBUILD = "projections:rebuild"


ALL_PERMISSIONS = frozenset(v for k, v in vars(Perm).items() if not k.startswith("_"))

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": ALL_PERMISSIONS,
    "manager": frozenset({
        Perm.PRODUCT_MANAGE, Perm.STOCK_RECEIVE, Perm.STOCK_DISPATCH, Perm.STOCK_ADJUST,
        Perm.INVENTORY_READ, Perm.REPORTS_READ, Perm.EVENTS_READ,
    }),
    "clerk": frozenset({Perm.STOCK_RECEIVE, Perm.STOCK_DISPATCH, Perm.INVENTORY_READ}),
    "viewer": frozenset({Perm.INVENTORY_READ, Perm.REPORTS_READ}),
}

ROLES = tuple(ROLE_PERMISSIONS)


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())


@dataclass(frozen=True)
class Principal:
    """The authenticated caller of a request."""

    username: str
    role: str

    def can(self, permission: str) -> bool:
        return has_permission(self.role, permission)


_bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Principal:
    """FastAPI dependency: who is calling? (401 if not logged in).

    The token proves *who* you are. Your *current* role and active flag are read
    from your user stream in the event store, so a role change or deactivation
    takes effect immediately instead of when the token expires.
    """
    # Imported here to avoid a circular import (user.py imports ROLES from this module).
    from inventory.auth.user import User

    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not logged in")
    try:
        claims = verify_token(credentials.credentials)
    except InvalidToken as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    user = AggregateRepository(EventStore(get_pool())).load(User, claims["sub"])
    if not user.exists or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account is disabled")
    return Principal(username=user.id, role=user.role)


def require(permission: str):
    """FastAPI dependency factory: `principal = Depends(require(Perm.STOCK_RECEIVE))`."""

    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.can(permission):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"role '{principal.role}' is not allowed to do this (needs '{permission}')",
            )
        return principal

    dependency.required_permission = permission
    return dependency
