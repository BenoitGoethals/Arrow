"""Web app configuration — environment-driven, frozen at import time."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WebConfig:
    backend_url: str
    public_api_prefix: str
    ws_base: str
    debug: bool

    @classmethod
    def from_env(cls) -> "WebConfig":
        backend_url = os.environ.get("ARROW_BACKEND_URL", "http://localhost:6001")
        public_api_prefix = "/api"
        public_backend = os.environ.get("ARROW_PUBLIC_BACKEND_URL", "").rstrip("/")
        ws_base = public_backend if public_backend else public_api_prefix
        debug = os.environ.get("FLASK_DEBUG", "0") == "1"
        return cls(
            backend_url=backend_url,
            public_api_prefix=public_api_prefix,
            ws_base=ws_base,
            debug=debug,
        )
