"""Flask web platform — composition root.

Wires config → infrastructure → application → presentation. Each layer is
swappable: tests pass a fake renderer or backend client through this factory.
"""

from __future__ import annotations

from flask import Flask, Response

from web.application.pages import PageService
from web.config import WebConfig
from web.infrastructure import security_headers
from web.infrastructure.backend_client import BackendClient, HttpxBackendClient
from web.infrastructure.template_renderer import FlaskTemplateRenderer, PageRenderer
from web.presentation import proxy_routes, shell_routes
from web.presentation.blueprints import (
    admin, apk, cas, cbrn, cbrncop, cop, cop_hub, dashboard, fire_missions, firescop,
    history, intcop, logcop, logrep, medcop, messaging, missions, objectives, opord,
    organisation, reports, streams, strike_packages, taccop, tactical_map, tracks, weather,
)


def create_app(
    config: WebConfig | None = None,
    *,
    service: PageService | None = None,
    renderer: PageRenderer | None = None,
    backend_client: BackendClient | None = None,
) -> Flask:
    cfg = config or WebConfig.from_env()
    service = service or PageService()
    renderer = renderer or FlaskTemplateRenderer()
    backend_client = backend_client or HttpxBackendClient(cfg.backend_url)

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["BACKEND_URL"] = cfg.backend_url

    # Ship web logs to the backend so the admin Logs viewer shows them, and log
    # every request. Uses the server-to-server backend URL (not the public prefix).
    import logging as _logging
    import os as _os
    import time as _time
    from flask import g, request
    try:
        from web.log_shipper import install as _install_shipper
        _install_shipper(cfg.backend_url, token=_os.environ.get("ARROW_LOG_TOKEN", ""))
    except Exception:
        pass
    _web_log = _logging.getLogger("web.request")

    @app.before_request
    def _t0() -> None:
        g._t0 = _time.monotonic()

    @app.after_request
    def _access_log(response: Response) -> Response:
        try:
            ms = (_time.monotonic() - getattr(g, "_t0", _time.monotonic())) * 1000
            _web_log.info("%s %s → %d (%.0f ms)", request.method, request.path,
                          response.status_code, ms)
        except Exception:
            pass
        return response

    for module in (
        dashboard, tactical_map, messaging, fire_missions, streams,
        reports, history, objectives, opord, admin, apk, tracks, missions,
        strike_packages, cas, organisation, cbrn, logrep,
        cbrncop, cop_hub, taccop, logcop, medcop, intcop, firescop, cop, weather,
    ):
        app.register_blueprint(module.build_blueprint(service, renderer))
    shell_routes.register(app, service, renderer)
    app.register_blueprint(proxy_routes.build_blueprint(backend_client, cfg.public_api_prefix))

    @app.after_request
    def _apply_security(response: Response) -> Response:
        return security_headers.apply(response)

    @app.context_processor
    def _inject_backend() -> dict:
        return {"backend_url": cfg.public_api_prefix, "ws_url": cfg.ws_base}

    return app


app = create_app()


def run() -> None:
    import os
    cfg = WebConfig.from_env()

    ssl_context = None
    if os.environ.get("ARROW_WEB_HTTP", "0") != "1":
        try:
            from web.ssl_cert import ensure_cert
            cert, key = ensure_cert()
            ssl_context = (cert, key)
            print(f"[Arrow Web] HTTPS on :6002  (cert: {cert})", flush=True)
            print("[Arrow Web] First visit: click 'Advanced → Proceed' to accept the cert", flush=True)
        except Exception as exc:
            print(f"[Arrow Web] TLS cert error ({exc}) — falling back to HTTP", flush=True)
    else:
        print("[Arrow Web] HTTP mode (ARROW_WEB_HTTP=1)", flush=True)

    app.run(host="0.0.0.0", port=6002, debug=cfg.debug, ssl_context=ssl_context)


if __name__ == "__main__":
    run()
