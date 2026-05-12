from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("reports", __name__, url_prefix="/reports")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.reports())

    return bp
