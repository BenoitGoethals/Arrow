from flask import Blueprint, render_template

bp = Blueprint("history", __name__, url_prefix="/history")


@bp.route("/")
def index() -> str:
    return render_template("history.html")
