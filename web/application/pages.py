"""Page use-cases.

One method per route. Each returns a PageView — a pure value the renderer
turns into HTML. Pure functions make it trivial to assert template + context
in unit tests, no Flask app needed.
"""

from __future__ import annotations

from web.domain.page import PageView


class PageService:
    def dashboard(self) -> PageView:
        return PageView("dashboard.html")

    def admin(self) -> PageView:
        return PageView("admin.html")

    def apk_download(self) -> PageView:
        return PageView("apk_download.html")

    def map(self) -> PageView:
        return PageView("map.html")

    def messaging(self) -> PageView:
        return PageView("messaging.html")

    def fire_missions(self) -> PageView:
        return PageView("fire_missions.html")

    def reports(self) -> PageView:
        return PageView("reports.html")

    def history(self) -> PageView:
        return PageView("history.html")

    def photos(self) -> PageView:
        return PageView("photos.html")

    def streams_index(self) -> PageView:
        return PageView("stream.html")

    def stream_recordings(self) -> PageView:
        return PageView("recordings.html")

    def stream_view(self, stream_id: str) -> PageView:
        return PageView("stream.html", {"stream_id": stream_id})

    def objectives_index(self) -> PageView:
        return PageView("objectives.html")

    def objective_detail(self, object_id: int) -> PageView:
        return PageView("objective_detail.html", {"object_id": object_id})

    def opord_list(self) -> PageView:
        return PageView("opord_list.html")

    def opord_new(self) -> PageView:
        return PageView("opord_editor.html", {"opord_id": ""})

    def opord_edit(self, opord_id: int) -> PageView:
        return PageView("opord_editor.html", {"opord_id": opord_id})

    def strike_packages(self) -> PageView:
        return PageView("strike_packages.html")

    def tracks(self) -> PageView:
        return PageView("tracks.html")

    def login(self) -> PageView:
        return PageView("login.html")

    def logout(self) -> PageView:
        return PageView("logout.html")

    def missions(self) -> PageView:
        return PageView("missions.html")

    def cas_capacity(self) -> PageView:
        return PageView("cas.html")

    def organisation(self) -> PageView:
        return PageView("organisation.html")

    def cbrn(self) -> PageView:
        return PageView("cbrn.html")

    def logrep(self) -> PageView:
        return PageView("logrep.html")

    def cbrncop(self) -> PageView:
        return PageView("cbrncop.html")

    def cop_hub(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "⊞", "cop_name": "COP Hub",
            "cop_desc": "Overview of all Common Operational Pictures.",
        })

    def taccop(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "🗺", "cop_name": "TACCOP — Tactical",
            "cop_desc": "Tactical Common Operational Picture.",
        })

    def logcop(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "📦", "cop_name": "LOGCOP — Logistics",
            "cop_desc": "Logistics Common Operational Picture.",
        })

    def medcop(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "🏥", "cop_name": "MEDCOP — Medical",
            "cop_desc": "Medical Common Operational Picture.",
        })

    def intcop(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "🔍", "cop_name": "INTCOP — Intelligence",
            "cop_desc": "Intelligence Common Operational Picture.",
        })

    def firescop(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "🔥", "cop_name": "FIRESCOP — Fire Support",
            "cop_desc": "Fire Support Common Operational Picture.",
        })

    def cop_docs(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "🗂", "cop_name": "COP Documents",
            "cop_desc": "Operational documents and annexes.",
        })

    def weather(self) -> PageView:
        return PageView("cop_stub.html", {
            "cop_icon": "⛅", "cop_name": "Weather",
            "cop_desc": "Meteorological and METOC data.",
        })
