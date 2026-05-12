from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("objectives", __name__, url_prefix="/objectives")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.objectives_index())

    @bp.route("/<int:object_id>")
    def detail(object_id: int) -> str:
        return renderer.render(service.objective_detail(object_id))

    return bp
