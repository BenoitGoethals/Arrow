"""Proxy uses a BackendClient port — swap it for a fake in tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from web.app import create_app
from web.config import WebConfig
from web.infrastructure.backend_client import ProxyResponse


@dataclass
class FakeBackend:
    calls: list[dict[str, Any]] = field(default_factory=list)
    response: ProxyResponse = field(
        default_factory=lambda: ProxyResponse(
            status_code=200,
            content=b'{"ok":true}',
            headers=[("content-type", "application/json")],
        )
    )

    def forward(self, method, path, *, params, body, headers) -> ProxyResponse:
        self.calls.append({"method": method, "path": path, "body": body})
        return self.response


def _cfg() -> WebConfig:
    return WebConfig(
        backend_url="http://unused",
        public_api_prefix="/api",
        ws_base="/api",
        debug=False,
    )


def test_proxy_forwards_to_backend_client() -> None:
    fake = FakeBackend()
    app = create_app(config=_cfg(), backend_client=fake)
    client = app.test_client()

    r = client.post("/api/auth/login", data=b"x=1")

    assert r.status_code == 200
    assert r.data == b'{"ok":true}'
    assert fake.calls == [{"method": "POST", "path": "auth/login", "body": b"x=1"}]


def test_proxy_returns_backend_status() -> None:
    fake = FakeBackend(
        response=ProxyResponse(status_code=404, content=b"nope", headers=[])
    )
    app = create_app(config=_cfg(), backend_client=fake)

    r = app.test_client().get("/api/missing")

    assert r.status_code == 404
