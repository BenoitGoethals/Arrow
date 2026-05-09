from flask import Blueprint, render_template
bp = Blueprint("streams", __name__, url_prefix="/streams")

@bp.route("/")
def index() -> str:
    return render_template("stream.html")

@bp.route("/recordings")
def recordings() -> str:
    return render_template("recordings.html")

@bp.route("/<stream_id>")
def view(stream_id: str) -> str:
    return render_template("stream.html", stream_id=stream_id)
