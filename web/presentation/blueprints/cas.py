from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("cas_capacity", __name__, url_prefix="/cas")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.cas_capacity())

    return bp
