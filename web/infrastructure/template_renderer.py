"""Adapter that turns a PageView into an HTTP response body via Flask templates."""

from __future__ import annotations

from typing import Protocol

from flask import render_template

from web.domain.page import PageView


class PageRenderer(Protocol):
    def render(self, view: PageView) -> str: ...


class FlaskTemplateRenderer:
    def render(self, view: PageView) -> str:
        return render_template(view.template, **view.context)
