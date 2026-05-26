from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("missions", __name__, url_prefix="/missions")

    @bp.route("/")
    def index():
        return renderer.render("missions.html")

    return bp
