"""Flask web platform — operational dashboard for Battle Captains and Admins."""

from __future__ import annotations

import json
import os

import httpx
from flask import Flask, Response, render_template, request

BACKEND_URL = os.environ.get("ARROW_BACKEND_URL", "http://localhost:6001")
PUBLIC_API_PREFIX = "/api"
# Browser-reachable backend base (for WebSocket).
# Dev: set ARROW_PUBLIC_BACKEND_URL=http://localhost:6001
# Prod (Docker+Caddy): leave unset — browser uses same-origin /api, Caddy proxies WS.
_PUBLIC_BACKEND = os.environ.get("ARROW_PUBLIC_BACKEND_URL", "").rstrip("/")
WS_BASE = _PUBLIC_BACKEND if _PUBLIC_BACKEND else PUBLIC_API_PREFIX
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    "content-encoding",
}


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["BACKEND_URL"] = BACKEND_URL

    from web.admin.routes import bp as admin_bp
    from web.dashboard.routes import bp as dashboard_bp
    from web.messaging.routes import bp as messaging_bp
    from web.fire_missions.routes import bp as fire_missions_bp
    from web.streams.routes import bp as streams_bp
    from web.reports.routes import bp as reports_bp
    from web.tactical_map.routes import bp as map_bp
    from web.history.routes import bp as history_bp
    from web.objectives.routes import bp as objectives_bp
    from web.opord.routes import bp as opord_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(messaging_bp)
    app.register_blueprint(fire_missions_bp)
    app.register_blueprint(streams_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(objectives_bp)
    app.register_blueprint(opord_bp)
    app.register_blueprint(admin_bp)

    @app.after_request
    def _security_headers(response: Response) -> Response:
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        # CSP: allows self + CDN (Leaflet, milsymbol on unpkg) + OSM tiles + WS
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com; "
            "img-src 'self' data: blob: https://*.tile.openstreetmap.org; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'"
        )
        return response

    @app.context_processor
    def _inject_backend() -> dict:
        # Browser talks to the proxy on the same origin; server-side templates
        # can still render absolute backend URLs via BACKEND_URL when needed.
        return {"backend_url": PUBLIC_API_PREFIX, "ws_url": WS_BASE}

    @app.route(
        f"{PUBLIC_API_PREFIX}/<path:subpath>",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    def _backend_proxy(subpath: str) -> Response:
        url = f"{BACKEND_URL}/{subpath}"
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        try:
            upstream = httpx.request(
                request.method,
                url,
                params=request.args,
                content=request.get_data(),
                headers=headers,
                timeout=30.0,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            body = json.dumps({"detail": f"Backend unreachable: {exc}"})
            return Response(body, status=502, content_type="application/json")
        out_headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP]
        return Response(upstream.content, status=upstream.status_code, headers=out_headers)

    @app.route("/")
    def index():
        from flask import redirect, url_for
        return redirect(url_for("dashboard.index"))

    @app.route("/login")
    def login() -> str:
        return render_template("login.html")

    @app.route("/logout")
    def logout() -> str:
        return render_template("logout.html")

    return app


app = create_app()


def run() -> None:
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=6002, debug=debug)


if __name__ == "__main__":
    run()
