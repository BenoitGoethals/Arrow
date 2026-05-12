"""Top-level shell routes: index redirect, login, logout.

Registered directly on the app (not via a Blueprint) so that templates
can use `url_for('login')` / `url_for('logout')` with bare endpoint names.
"""

from __future__ import annotations

from flask import Flask, redirect, url_for

from web.application.pages import PageService
from web.infrastructure.template_renderer import PageRenderer


def register(app: Flask, service: PageService, renderer: PageRenderer) -> None:
    @app.route("/", endpoint="index")
    def index():
        return redirect(url_for("dashboard.index"))

    @app.route("/login", endpoint="login")
    def login() -> str:
        return renderer.render(service.login())

    @app.route("/logout", endpoint="logout")
    def logout() -> str:
        return renderer.render(service.logout())
