"""Flask web platform — operational dashboard for Battle Captains and Admins."""

from __future__ import annotations

import os

from flask import Flask, render_template

BACKEND_URL = os.environ.get("ARROW_BACKEND_URL", "http://localhost:6001")


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["BACKEND_URL"] = BACKEND_URL

    from web.admin.routes import bp as admin_bp
    from web.dashboard.routes import bp as dashboard_bp
    from web.messaging.routes import bp as messaging_bp
    from web.tactical_map.routes import bp as map_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(map_bp)
    app.register_blueprint(messaging_bp)
    app.register_blueprint(admin_bp)

    @app.context_processor
    def _inject_backend() -> dict:
        return {"backend_url": app.config["BACKEND_URL"]}

    @app.route("/")
    def index() -> str:
        return render_template("index.html")

    @app.route("/login")
    def login() -> str:
        return render_template("login.html")

    @app.route("/logout")
    def logout() -> str:
        return render_template("logout.html")

    return app


app = create_app()


def run() -> None:
    app.run(host="0.0.0.0", port=6002, debug=True)


if __name__ == "__main__":
    run()
