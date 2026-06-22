"""Reverse-proxy blueprint forwarding /api/* to the FastAPI backend."""

from __future__ import annotations

from flask import Blueprint, Response, request

from web.infrastructure.backend_client import BackendClient


def build_blueprint(client: BackendClient, prefix: str) -> Blueprint:
    bp = Blueprint("proxy", __name__)

    @bp.route(
        f"{prefix}/<path:subpath>",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    def forward(subpath: str) -> Response:
        result = client.forward(
            request.method,
            subpath,
            params=list(request.args.items(multi=True)) or None,
            body=request.get_data(),
            headers={k: v for k, v in request.headers.items()},
        )
        return Response(
            result.content, status=result.status_code, headers=result.headers
        )

    return bp
