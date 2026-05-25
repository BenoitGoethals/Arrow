"""Security header policy applied to every response."""

from __future__ import annotations

from flask import Response

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline' https://unpkg.com; "
    "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
    "media-src 'self' blob:; "
    "connect-src 'self' ws: wss:; "
    "frame-ancestors 'none'"
)

_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
    "Content-Security-Policy": _CSP,
}


def apply(response: Response) -> Response:
    for k, v in _HEADERS.items():
        response.headers[k] = v
    return response
