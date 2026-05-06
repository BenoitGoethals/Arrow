from flask import Blueprint, render_template

bp = Blueprint("tactical_map", __name__, url_prefix="/map")


@bp.route("/")
def index() -> str:
    return render_template("map.html")
