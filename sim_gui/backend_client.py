"""Auto-refreshing admin client.

Wraps `sim_utils.Api` so every admin-scoped HTTP call retries once after a
401. The Arrow backend invalidates `op.session_jti` on every successful
`/auth/login` for that callsign (`backend/auth/dependencies.py:44`,
`backend/auth/application/auth_service.py:200`), which means anyone else
logging in as `benoit` (web dashboard, another GUI, a CI job) supersedes our
admin token mid-run. Rather than ask the user to fix the parallel login, we
just re-login transparently when we see "Session superseded".

`AdminSession` keeps the same surface as `sim_utils.Api` (`get`/`post`/
`patch`/`delete`/`create_mission`) so it's a drop-in replacement everywhere
the facade and scenarios pass an `Api`. The token argument is accepted for
signature compatibility but ignored — the session always uses its current
admin token.

`post_raw()` is the escape hatch for callers that need the raw
`httpx.Response` (the hierarchy seeder uses it for `/auth/register/admin`
because that endpoint returns both 201 with the new operator's token and
non-2xx for already-exists — both are meaningful).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import httpx

from sim_utils import Api

log = logging.getLogger("sim.session")


@dataclass(slots=True)
class BackendCredentials:
    base_url: str
    admin_callsign: str
    admin_password: str


@dataclass(slots=True)
class AdminSession:
    """Self-refreshing admin context. Same surface as `sim_utils.Api`."""

    api: Api
    creds: BackendCredentials
    token: str
    _refresh_count: int = field(default=0)

    # ── construction ──────────────────────────────────────────────────────

    @classmethod
    def open(cls, creds: BackendCredentials) -> AdminSession:
        api = Api(creds.base_url)
        tok = api.login(creds.admin_callsign, creds.admin_password)
        return cls(api=api, creds=creds, token=tok)

    def refresh(self) -> None:
        self.token = self.api.login(
            self.creds.admin_callsign, self.creds.admin_password
        )
        self._refresh_count += 1
        log.info("admin session refreshed (#%d)", self._refresh_count)

    # ── helpers ───────────────────────────────────────────────────────────

    def _with_retry(self, call: Callable[[str], Any]) -> Any:
        try:
            return call(self.token)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 401:
                raise
            self.refresh()
            return call(self.token)

    # ── Api-compatible surface ────────────────────────────────────────────

    @property
    def c(self) -> httpx.Client:
        return self.api.c

    @property
    def mission_id(self) -> int | None:
        return self.api.mission_id

    @mission_id.setter
    def mission_id(self, v: int | None) -> None:
        self.api.mission_id = v

    def _p(self, path: str) -> str:
        return self.api._p(path)

    def get(self, path: str, _tok: str | None = None) -> object:
        return self._with_retry(lambda tok: self.api.get(path, tok))

    def post(self, path: str, _tok: str, body: dict) -> object:
        return self._with_retry(lambda tok: self.api.post(path, tok, body))

    def patch(self, path: str, _tok: str, body: dict) -> object:
        return self._with_retry(lambda tok: self.api.patch(path, tok, body))

    def delete(self, path: str, _tok: str | None = None) -> int:
        return cast(int, self._with_retry(lambda tok: self.api.delete(path, tok)))

    def create_mission(
        self,
        _tok: str | None = None,
        name: str = "",
        description: str = "",
        map_center_lat: float | None = None,
        map_center_lng: float | None = None,
        map_zoom: int = 13,
    ) -> int | None:
        def call(tok: str) -> int | None:
            return self.api.create_mission(
                tok,
                name,
                description=description,
                map_center_lat=map_center_lat,
                map_center_lng=map_center_lng,
                map_zoom=map_zoom,
            )

        return cast(int | None, self._with_retry(call))

    # Operator (non-admin) login passes through unchanged — the seeder uses
    # it to log in newly-registered operators, which must NOT use the admin's
    # token.
    def login(self, callsign: str, password: str) -> str:
        return self.api.login(callsign, password)

    # ── escape hatch for raw response shape ───────────────────────────────

    def post_raw(self, path: str, body: dict) -> httpx.Response:
        """POST + return raw httpx.Response so the caller can branch on
        status code (e.g. 201 vs 409). Still retries on 401."""

        def call() -> httpx.Response:
            return self.api.c.post(
                self.api._p(path),
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
            )

        r = call()
        if r.status_code == 401:
            self.refresh()
            r = call()
        return r


# ── legacy helper (kept for tests / external callers) ────────────────────────


def connect(creds: BackendCredentials) -> tuple[Api, str]:
    api = Api(creds.base_url)
    token = api.login(creds.admin_callsign, creds.admin_password)
    return api, token
