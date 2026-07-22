"""Kivy App — screen manager wiring LoginScreen -> MainScreen."""

from __future__ import annotations

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager, NoTransition

from front_kivy.app.login_screen import LoginScreen
from front_kivy.app.main_screen import MainScreen


class ArrowFrontKivyApp(App):
    title = "Arrow Front (Kivy)"

    def build(self):
        Window.size = (1280, 800)
        Window.clearcolor = (0.05, 0.07, 0.09, 1)

        self.sm = ScreenManager(transition=NoTransition())
        login = LoginScreen(on_connected=self._on_connected, name="login")
        self.sm.add_widget(login)
        return self.sm

    def _on_connected(self, server_url: str, token: str, callsign: str):
        main_screen = MainScreen(server_url, token, callsign, name="main")
        self.sm.add_widget(main_screen)
        self.sm.current = "main"

    def on_stop(self):
        main_screen = (
            self.sm.get_screen("main") if "main" in self.sm.screen_names else None
        )
        if isinstance(main_screen, MainScreen):
            main_screen.stop()
