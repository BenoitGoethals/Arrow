"""Login screen — Kivy port of front/app/login_dialog.py.

Same fields/flow (server URL, callsign, password, remember-me, skip), same
ArrowClient.login() + keyring-backed token storage, but as a Kivy Screen
instead of a QDialog, with the network call run on a background thread (the
Kivy main thread must never block on I/O) and the result marshaled back via
Clock, matching the pattern used everywhere else in front_kivy.
"""

from __future__ import annotations

import threading

import httpx
from kivy.clock import Clock
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.screenmanager import Screen
from kivy.uix.textinput import TextInput

from front.client import auth as keyring_auth
from front.client.arrow_client import ArrowClient
from front_kivy.app import settings_store

_DEFAULT_URL = "http://localhost:6001"


class LoginScreen(Screen):
    error_text = StringProperty("")

    def __init__(self, on_connected, **kwargs):
        """`on_connected(server_url, token, callsign)` is called once login
        (or skip) succeeds."""
        super().__init__(**kwargs)
        self._on_connected = on_connected
        self._build_ui()
        self._restore_fields()

    def _build_ui(self):
        root = BoxLayout(orientation="vertical", padding=32, spacing=12)

        root.add_widget(
            Label(
                text="ARROW FRONT — CONNECT", font_size=20, size_hint_y=None, height=40
            )
        )
        root.add_widget(
            Label(
                text="COMMON OPERATIONAL PICTURE",
                font_size=11,
                size_hint_y=None,
                height=20,
            )
        )

        self._url_field = TextInput(
            hint_text="server URL", multiline=False, size_hint_y=None, height=36
        )
        self._callsign_field = TextInput(
            hint_text="callsign", multiline=False, size_hint_y=None, height=36
        )
        self._password_field = TextInput(
            hint_text="password",
            password=True,
            multiline=False,
            size_hint_y=None,
            height=36,
        )
        for f in (self._url_field, self._callsign_field, self._password_field):
            root.add_widget(f)

        self._error_label = Label(
            text="", color=(1, 0.3, 0.3, 1), size_hint_y=None, height=24
        )
        root.add_widget(self._error_label)

        self._connect_btn = Button(text="CONNECT", size_hint_y=None, height=44)
        self._connect_btn.bind(on_release=lambda *_: self._do_login())
        root.add_widget(self._connect_btn)

        skip_btn = Button(text="Continue without login", size_hint_y=None, height=32)
        skip_btn.bind(on_release=lambda *_: self._do_skip())
        root.add_widget(skip_btn)

        root.add_widget(Label())  # spacer
        self.add_widget(root)

    def _restore_fields(self):
        saved = settings_store.load()
        self._url_field.text = saved.get("server_url", _DEFAULT_URL)
        self._callsign_field.text = saved.get("last_callsign", "")

    def _save_fields(self):
        settings_store.save(
            {
                "server_url": self._normalize_url(self._url_field.text),
                "last_callsign": self._callsign_field.text.strip(),
            }
        )

    @staticmethod
    def _normalize_url(raw: str) -> str:
        return raw.strip().rstrip("/")

    def _do_login(self):
        url = self._normalize_url(self._url_field.text)
        callsign = self._callsign_field.text.strip()
        password = self._password_field.text

        if not url or not callsign or not password:
            self._error_label.text = "All fields are required"
            return

        self._error_label.text = ""
        self._connect_btn.disabled = True
        self._connect_btn.text = "CONNECTING…"

        threading.Thread(
            target=self._login_worker, args=(url, callsign, password), daemon=True
        ).start()

    def _login_worker(self, url: str, callsign: str, password: str):
        try:
            client = ArrowClient(url)
            data = client.login(callsign, password)
            Clock.schedule_once(
                lambda dt: self._on_login_success(url, callsign, data["access_token"])
            )
        except httpx.TimeoutException:
            Clock.schedule_once(
                lambda dt: self._on_login_error(
                    "Server timed out — check URL and network"
                )
            )
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg:
                err = "Invalid credentials"
            elif "connect" in msg.lower():
                err = "Cannot reach server"
            else:
                err = f"Error: {msg[:60]}"
            Clock.schedule_once(lambda dt: self._on_login_error(err))

    def _on_login_success(self, url: str, callsign: str, token: str):
        self._save_fields()
        keyring_auth.save_token(url, token)
        self._connect_btn.disabled = False
        self._connect_btn.text = "CONNECT"
        self._on_connected(url, token, callsign)

    def _on_login_error(self, message: str):
        self._error_label.text = message
        self._connect_btn.disabled = False
        self._connect_btn.text = "CONNECT"

    def _do_skip(self):
        url = self._normalize_url(self._url_field.text) or _DEFAULT_URL
        self._save_fields()
        self._on_connected(url, "", "GUEST")
