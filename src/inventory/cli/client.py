"""HTTP client for the two APIs, plus the logged-in session.

Commands go to the command-api (write side), queries go to the query-api (read
side). The client never mixes them up: that split IS CQRS, seen from the outside.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from rich.console import Console

from inventory.config import settings


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _detail(response: httpx.Response) -> str:
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        return response.text or response.reason_phrase
    if isinstance(detail, list):  # FastAPI validation errors
        return "; ".join(f"{'.'.join(str(p) for p in d.get('loc', [])[1:])}: {d.get('msg')}" for d in detail)
    return str(detail)


class ApiClient:
    def __init__(
        self,
        command_url: str | None = None,
        query_url: str | None = None,
        command_http: httpx.Client | None = None,
        query_http: httpx.Client | None = None,
    ):
        # The *_http parameters let tests plug in FastAPI TestClients instead of real HTTP.
        self.command_http = command_http or httpx.Client(base_url=command_url or settings.command_api_url, timeout=15)
        self.query_http = query_http or httpx.Client(base_url=query_url or settings.query_api_url, timeout=15)
        self.token: str | None = None

    def _send(self, http: httpx.Client, method: str, path: str, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = http.request(method, path, headers=headers, **kwargs)
        except httpx.TransportError as exc:
            raise ApiError(0, f"cannot reach {http.base_url} - is the service running? ({exc})") from exc
        if response.status_code >= 400:
            raise ApiError(response.status_code, _detail(response))
        return response.json()

    def send_command(self, method: str, path: str, body: dict | None = None) -> dict:
        return self._send(self.command_http, method, path, json=body or {})

    def query(self, path: str, **params) -> dict | list:
        params = {k: v for k, v in params.items() if v is not None}
        return self._send(self.query_http, "GET", path, params=params)

    def admin_post(self, path: str) -> dict:
        return self._send(self.query_http, "POST", path)

    def login(self, username: str, password: str) -> dict:
        return self._send(self.command_http, "POST", "/auth/login", json={"username": username, "password": password})

    def wait_for_projection(self, position: int, timeout: float = 5.0) -> bool:
        """Read-your-writes: poll until the projector has applied `position`."""
        deadline = time.monotonic() + timeout
        while True:
            if self.query("/status")["checkpoint"] >= position:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)


def _session_file() -> Path:
    return Path(os.getenv("INVENTORY_SESSION_FILE", Path.home() / ".inventory_session.json"))


@dataclass
class Session:
    """Everything a CLI command needs: the API client, who is logged in, and the console."""

    api: ApiClient
    console: Console = field(default_factory=Console)
    username: str | None = None
    role: str | None = None
    persist: bool = True

    def set_login(self, token: str, username: str, role: str) -> None:
        self.api.token, self.username, self.role = token, username, role
        if self.persist:
            _session_file().write_text(json.dumps({"token": token, "username": username, "role": role}))

    def clear_login(self) -> None:
        self.api.token = self.username = self.role = None
        if self.persist:
            _session_file().unlink(missing_ok=True)

    def restore(self) -> None:
        """Reuse the token from the last login so one-shot commands work across runs."""
        if not self.persist:
            return
        try:
            saved = json.loads(_session_file().read_text())
        except (OSError, ValueError):
            return
        self.api.token, self.username, self.role = saved.get("token"), saved.get("username"), saved.get("role")
