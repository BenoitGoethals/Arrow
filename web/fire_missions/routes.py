from flask import Blueprint, render_template

bp = Blueprint("fire_missions", __name__, url_prefix="/fire-missions")


@bp.route("/")
def index() -> str:
    return render_template("fire_missions.html")
