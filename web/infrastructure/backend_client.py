"""HTTP adapter to the FastAPI backend.

Used by the /api reverse proxy. Kept behind a Protocol so tests can swap it
for an in-memory fake without touching the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
        "content-encoding",
    }
)


@dataclass(frozen=True)
class ProxyResponse:
    status_code: int
    content: bytes
    headers: list[tuple[str, str]]


class BackendClient(Protocol):
    def forward(
        self,
        method: str,
        path: str,
        *,
        params: Any | None,
        body: bytes,
        headers: dict[str, str],
    ) -> ProxyResponse: ...


class HttpxBackendClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def forward(
        self,
        method: str,
        path: str,
        *,
        params: Any | None,
        body: bytes,
        headers: dict[str, str],
    ) -> ProxyResponse:
        safe_headers = {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            upstream = httpx.request(
                method,
                url,
                params=params,
                content=body,
                headers=safe_headers,
                timeout=self._timeout,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            import json

            return ProxyResponse(
                status_code=502,
                content=json.dumps({"detail": f"Backend unreachable: {exc}"}).encode(),
                headers=[("content-type", "application/json")],
            )
        out_headers = [
            (k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP
        ]
        return ProxyResponse(
            status_code=upstream.status_code,
            content=upstream.content,
            headers=out_headers,
        )
