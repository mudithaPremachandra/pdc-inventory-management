# Owner: Sandun (Authentication and access management).
"""The User aggregate: users are event-sourced exactly like products.

Stream id is `user-<username>`, so "username already taken" is enforced by the
event store itself: registering appends with expected_version 0, which fails if
the stream already has events.
"""

import re
from dataclasses import dataclass

from inventory.auth.permissions import ROLES
from inventory.domain.aggregate import AggregateRoot
from inventory.domain.errors import AlreadyExists, DomainError, InvalidInput, NotFound
from inventory.domain.events import DomainEvent, register_event

USERNAME_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{2,31}$")


def normalise_username(username: str) -> str:
    username = (username or "").strip().lower()
    if not USERNAME_PATTERN.match(username):
        raise InvalidInput("username must be 3-32 chars, start with a letter, and use a-z 0-9 _ . -")
    return username


def _role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in ROLES:
        raise InvalidInput(f"unknown role {role!r}; choose one of: {', '.join(ROLES)}")
    return role


# --- User events --------------------------------------------------------------


@register_event
@dataclass(frozen=True)
class UserRegistered(DomainEvent):
    username: str
    role: str
    password_hash: str


@register_event
@dataclass(frozen=True)
class UserRoleChanged(DomainEvent):
    username: str
    old_role: str
    new_role: str


@register_event
@dataclass(frozen=True)
class UserPasswordChanged(DomainEvent):
    username: str
    password_hash: str


@register_event
@dataclass(frozen=True)
class UserDeactivated(DomainEvent):
    username: str


@register_event
@dataclass(frozen=True)
class UserReactivated(DomainEvent):
    username: str


# --- Aggregate ----------------------------------------------------------------


class User(AggregateRoot):
    stream_type = "user"

    def __init__(self, username: str):
        super().__init__(username)
        self.role = ""
        self.password_hash = ""
        self.active = False

    def register(self, role: str, password_hash: str) -> None:
        if self.exists:
            raise AlreadyExists(f"user {self.id} already exists")
        self._record(UserRegistered(username=self.id, role=_role(role), password_hash=password_hash))

    def change_role(self, role: str) -> None:
        self._ensure_exists()
        role = _role(role)
        if role == self.role:
            raise DomainError(f"user {self.id} already has role {role}")
        self._record(UserRoleChanged(username=self.id, old_role=self.role, new_role=role))

    def change_password(self, password_hash: str) -> None:
        self._ensure_exists()
        self._record(UserPasswordChanged(username=self.id, password_hash=password_hash))

    def deactivate(self) -> None:
        self._ensure_exists()
        if not self.active:
            raise DomainError(f"user {self.id} is already deactivated")
        self._record(UserDeactivated(username=self.id))

    def reactivate(self) -> None:
        self._ensure_exists()
        if self.active:
            raise DomainError(f"user {self.id} is already active")
        self._record(UserReactivated(username=self.id))

    def _ensure_exists(self) -> None:
        if not self.exists:
            raise NotFound(f"user {self.id} does not exist")

    def on_UserRegistered(self, e: UserRegistered) -> None:
        self.role = e.role
        self.password_hash = e.password_hash
        self.active = True

    def on_UserRoleChanged(self, e: UserRoleChanged) -> None:
        self.role = e.new_role

    def on_UserPasswordChanged(self, e: UserPasswordChanged) -> None:
        self.password_hash = e.password_hash

    def on_UserDeactivated(self, e: UserDeactivated) -> None:
        self.active = False

    def on_UserReactivated(self, e: UserReactivated) -> None:
        self.active = True
