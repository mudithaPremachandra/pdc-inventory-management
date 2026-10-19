
"""Login and user-management endpoints, mounted on the command-api.

User changes are commands like any other: they go through the same
load -> decide -> append handler and end up as events in the store.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from inventory.auth.passwords import hash_password, verify_password
from inventory.auth.permissions import Perm, Principal, current_principal, require
from inventory.auth.tokens import issue_token
from inventory.auth.user import User, normalise_username
from inventory.commands.handlers import CommandHandler, CommandResult
from inventory.config import settings
from inventory.db import get_pool
from inventory.domain.errors import AlreadyExists, ConcurrencyError, DomainError
from inventory.eventstore.repository import AggregateRepository
from inventory.eventstore.store import EventStore

router = APIRouter()


def _handler() -> CommandHandler:
    return CommandHandler(AggregateRepository(EventStore(get_pool())))


def seed_admin(handler: CommandHandler) -> None:
    """Create the first admin from ADMIN_USERNAME / ADMIN_PASSWORD if it does not exist."""
    username = normalise_username(settings.admin_username)
    password_hash = hash_password(settings.admin_password)
    try:
        handler.execute(User, username, lambda u: u.register("admin", password_hash), "system", "SeedAdmin")
    except (AlreadyExists, ConcurrencyError):
        pass  # already seeded (or another instance seeded it at the same moment)


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class RegisterUserIn(BaseModel):
    username: str
    password: str
    role: str


class ChangeRoleIn(BaseModel):
    role: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


@router.post("/auth/login")
def login(body: LoginIn, handler: CommandHandler = Depends(_handler)) -> LoginOut:
    try:
        username = normalise_username(body.username)
    except DomainError:
        username = ""
    user = handler.repository.load(User, username) if username else None
    # Same message for "no such user" and "wrong password", so usernames can't be probed.
    if user is None or not user.exists or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    if not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "account is disabled")
    return LoginOut(access_token=issue_token(user.id, user.role), username=user.id, role=user.role)


@router.post("/auth/password", status_code=202)
def change_own_password(
    body: ChangePasswordIn,
    who: Principal = Depends(current_principal),
    handler: CommandHandler = Depends(_handler),
) -> CommandResult:
    user = handler.repository.load(User, who.username)
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "old password is wrong")
    new_hash = hash_password(body.new_password)
    return handler.execute(User, who.username, lambda u: u.change_password(new_hash), who.username, "ChangePassword")


@router.post("/users", status_code=202)
def register_user(
    body: RegisterUserIn,
    who: Principal = Depends(require(Perm.USERS_MANAGE)),
    handler: CommandHandler = Depends(_handler),
) -> CommandResult:
    username = normalise_username(body.username)
    password_hash = hash_password(body.password)
    return handler.execute(User, username, lambda u: u.register(body.role, password_hash), who.username, "RegisterUser")


@router.post("/users/{username}/role", status_code=202)
def change_role(
    username: str,
    body: ChangeRoleIn,
    who: Principal = Depends(require(Perm.USERS_MANAGE)),
    handler: CommandHandler = Depends(_handler),
) -> CommandResult:
    username = normalise_username(username)
    if username == who.username:
        raise DomainError("you cannot change your own role")
    return handler.execute(User, username, lambda u: u.change_role(body.role), who.username, "ChangeUserRole")


@router.post("/users/{username}/deactivate", status_code=202)
def deactivate_user(
    username: str,
    who: Principal = Depends(require(Perm.USERS_MANAGE)),
    handler: CommandHandler = Depends(_handler),
) -> CommandResult:
    username = normalise_username(username)
    if username == who.username:
        raise DomainError("you cannot deactivate your own account")
    return handler.execute(User, username, lambda u: u.deactivate(), who.username, "DeactivateUser")


@router.post("/users/{username}/reactivate", status_code=202)
def reactivate_user(
    username: str,
    who: Principal = Depends(require(Perm.USERS_MANAGE)),
    handler: CommandHandler = Depends(_handler),
) -> CommandResult:
    username = normalise_username(username)
    return handler.execute(User, username, lambda u: u.reactivate(), who.username, "ReactivateUser")
