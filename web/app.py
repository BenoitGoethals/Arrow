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
    admin, apk, cas, cbrn, cop, cop_hub, cbrncop, dashboard, fire_missions, firescop,
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

    for module in (
        dashboard, tactical_map, messaging, fire_missions, streams,
        reports, history, objectives, opord, admin, apk, tracks, missions,
        strike_packages, cas, organisation, cbrn, logrep, cop, weather, logcop,
        cop_hub, taccop, medcop, intcop, firescop, cbrncop,
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
    cfg = WebConfig.from_env()
    app.run(host="0.0.0.0", port=6002, debug=cfg.debug)


if __name__ == "__main__":
    run()
