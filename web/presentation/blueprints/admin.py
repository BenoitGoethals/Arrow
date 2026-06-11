from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("admin", __name__, url_prefix="/admin")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.admin())

    return bp
