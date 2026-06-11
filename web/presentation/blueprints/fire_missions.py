from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("fire_missions", __name__, url_prefix="/fire-missions")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.fire_missions())

    return bp
