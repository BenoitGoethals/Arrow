"""Unit tests for the web application layer.

PageService is pure — no Flask, no HTTP. We assert template + context.
"""

from __future__ import annotations

import pytest

from web.application.pages import PageService
from web.domain.page import PageView


@pytest.fixture
def service() -> PageService:
    return PageService()


def test_dashboard(service: PageService) -> None:
    assert service.dashboard() == PageView("dashboard.html")


def test_admin(service: PageService) -> None:
    assert service.admin() == PageView("admin.html")


def test_map(service: PageService) -> None:
    assert service.map() == PageView("map.html")


def test_stream_view_carries_id(service: PageService) -> None:
    assert service.stream_view("abc") == PageView("stream.html", {"stream_id": "abc"})


def test_objective_detail_carries_id(service: PageService) -> None:
    assert service.objective_detail(42) == PageView(
        "objective_detail.html", {"object_id": 42}
    )


def test_opord_new_blank_id(service: PageService) -> None:
    assert service.opord_new() == PageView("opord_editor.html", {"opord_id": ""})


def test_opord_edit_with_id(service: PageService) -> None:
    assert service.opord_edit(7) == PageView("opord_editor.html", {"opord_id": 7})
