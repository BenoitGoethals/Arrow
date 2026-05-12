from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("opord", __name__, url_prefix="/opord")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.opord_list())

    @bp.route("/new")
    def new() -> str:
        return renderer.render(service.opord_new())

    @bp.route("/<int:opord_id>")
    def edit(opord_id: int) -> str:
        return renderer.render(service.opord_edit(opord_id))

    return bp
