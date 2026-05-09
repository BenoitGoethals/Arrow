from flask import Blueprint, render_template

bp = Blueprint("objectives", __name__, url_prefix="/objectives")


@bp.route("/")
def index() -> str:
    return render_template("objectives.html")


@bp.route("/<int:object_id>")
def detail(object_id: int) -> str:
    return render_template("objective_detail.html", object_id=object_id)
