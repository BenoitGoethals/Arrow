from flask import Blueprint, render_template

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/")
def index() -> str:
    return render_template("admin.html")
