from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("cops", __name__, url_prefix="/cops")

    @bp.route("/cbrn/")
    def cbrn() -> str:
        return renderer.render(service.cbrncop())

    return bp
