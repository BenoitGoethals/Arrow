"""Flask blueprint serving the OPORD list, editor and viewer.

Frontend talks directly to the backend via the existing /api proxy and
the JWT in localStorage; Flask just renders shells.
"""

from flask import Blueprint, render_template

bp = Blueprint("opord", __name__, url_prefix="/opord")


@bp.route("/")
def index() -> str:
    return render_template("opord_list.html")


@bp.route("/new")
def new() -> str:
    return render_template("opord_editor.html", opord_id="")


@bp.route("/<int:opord_id>")
def edit(opord_id: int) -> str:
    return render_template("opord_editor.html", opord_id=opord_id)
