from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("strike_packages", __name__, url_prefix="/strike-packages")

    @bp.route("/")
    def index():
        return renderer.render(service.strike_packages())

    return bp
