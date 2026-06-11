from __future__ import annotations

from flask import Blueprint

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def build_blueprint(service: PageService, renderer: PageRenderer) -> Blueprint:
    bp = Blueprint("streams", __name__, url_prefix="/streams")

    @bp.route("/")
    def index() -> str:
        return renderer.render(service.streams_index())

    @bp.route("/recordings")
    def recordings() -> str:
        return renderer.render(service.stream_recordings())

    @bp.route("/<stream_id>")
    def view(stream_id: str) -> str:
        return renderer.render(service.stream_view(stream_id))

    return bp
