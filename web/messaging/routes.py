from flask import Blueprint, render_template

bp = Blueprint("messaging", __name__, url_prefix="/messaging")


@bp.route("/")
def index() -> str:
    return render_template("messaging.html")
