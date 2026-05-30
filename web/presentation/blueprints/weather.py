from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("weather", __name__, url_prefix="/weather")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.weather())

    return bp
