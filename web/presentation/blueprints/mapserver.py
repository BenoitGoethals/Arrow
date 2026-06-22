from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("mapserver", __name__, url_prefix="/mapserver-viewer")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.mapserver())

    return bp
