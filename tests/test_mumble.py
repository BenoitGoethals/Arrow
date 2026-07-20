"""Tests for the Mumble voice feature.

Covers the parts that run without a live Mumble server:

* ``backend.mumble.opus_fix`` — the libopus / ssl / opuslib-stub compatibility shim.
* ``backend.mumble.monitor.MumbleMonitor`` — config persistence, password masking,
  the pure ``_snapshot`` state builder, and start/stop lifecycle with pymumble mocked.
* The ``/mumble/*`` REST endpoints (status / config / ping) — auth, role gating, and
  the TCP probe — driven through the FastAPI ``TestClient``.
* ``front.mumble.client`` audio helpers (``_AudioOut`` mixing, ``_AudioIn`` PTT gate,
  ``list_audio_devices``) — no Qt event loop, no real audio device required.

Anything that needs a real Murmur (an actual voice handshake, end-to-end audio) is out of
scope here and belongs to the live smoke-test (``test_mumble.py`` at the repo root).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from tests.conftest import admin_token, auth, register

# ─────────────────────────────────────────────────────────────────────────────
# Test doubles
# ─────────────────────────────────────────────────────────────────────────────


class _FakeMumble:
    """Stand-in for pymumble_py3.Mumble — connects instantly, never touches a socket."""

    def __init__(self, host, username, password="", port=64738, reconnect=False, **_):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.channels = {0: {"name": "Root", "parent": -1}}
        self.users = {
            1: {
                "name": username,
                "channel_id": 0,
                "self_mute": False,
                "self_deaf": False,
            }
        }
        self._app = ""
        self.started = False
        self.stopped = False

    def set_application_string(self, s):
        self._app = s

    def start(self):
        self.started = True

    def is_ready(self):
        return True

    def stop(self):
        self.stopped = True


@pytest.fixture
def mumble_env(monkeypatch, tmp_path):
    """Isolate the ``monitor`` singleton: temp config path, mocked pymumble, clean state.

    Ordered before the ``client`` fixture in test signatures so the app lifespan's
    ``monitor.load_config()`` sees an empty temp config and never dials a real server.
    """
    from backend.mumble import monitor as mon

    monkeypatch.setattr(mon, "CONFIG_PATH", tmp_path / "mumble_config.json")
    monkeypatch.setattr(mon.pymumble, "Mumble", _FakeMumble, raising=False)
    monkeypatch.setattr(mon, "_AVAILABLE", True, raising=False)

    m = mon.monitor
    m._stop_connection()
    m._config = {}
    m._state = {"connected": False, "error": "", "channels": [], "users": []}

    yield m

    m._stop_connection()
    m._config = {}


# ─────────────────────────────────────────────────────────────────────────────
# 1. opus_fix compatibility shim
# ─────────────────────────────────────────────────────────────────────────────


def test_opus_fix_exposes_flags():
    import backend.mumble.opus_fix as ofx

    assert isinstance(ofx.OPUS_STUB_ACTIVE, bool)
    assert isinstance(ofx.OPUS_INSTALL_HINT, str)
    # The hint is only populated when the real library is missing (stub active).
    assert bool(ofx.OPUS_INSTALL_HINT) == ofx.OPUS_STUB_ACTIVE


def test_opus_fix_makes_opuslib_importable():
    # Importing the shim must guarantee `import opuslib` works — either the real
    # wrapper (libopus present) or the pure-Python silent stub.
    import backend.mumble.opus_fix  # noqa: F401

    opuslib = __import__("opuslib")
    enc = opuslib.Encoder(48000, 1, opuslib.APPLICATION_VOIP)
    dec = opuslib.Decoder(48000, 1)
    assert enc is not None and dec is not None


def test_opus_fix_restores_ssl_protocol_constants():
    # Python 3.12+ removed these; the shim must add them back so pymumble's TLS works.
    import backend.mumble.opus_fix  # noqa: F401
    import ssl

    assert hasattr(ssl, "PROTOCOL_TLS")


# ─────────────────────────────────────────────────────────────────────────────
# 2. MumbleMonitor — pure logic
# ─────────────────────────────────────────────────────────────────────────────


def test_snapshot_builds_channels_and_users():
    from backend.mumble.monitor import MumbleMonitor

    m = _FakeMumble("h", "BOT")
    m.channels = {
        0: {"name": "Root", "parent": -1},
        3: {"name": "Alpha", "parent": 0},
    }
    m.users = {
        1: {"name": "BOT", "channel_id": 0, "mute": False, "deaf": False},
        2: {"name": "OPS1", "channel_id": 3, "self_mute": True, "self_deaf": False},
    }
    channels, users = MumbleMonitor._snapshot(m)

    assert {c["id"] for c in channels} == {0, 3}
    alpha = next(c for c in channels if c["id"] == 3)
    assert alpha == {"id": 3, "name": "Alpha", "parent_id": 0}

    ops1 = next(u for u in users if u["session"] == 2)
    assert ops1["name"] == "OPS1"
    assert ops1["channel_id"] == 3
    assert ops1["muted"] is True  # self_mute counts as muted
    assert ops1["deafened"] is False


def test_get_config_public_masks_password(mumble_env):
    mumble_env._config = {"host": "murmur", "port": 64738, "password": "R@nger&1401!"}
    pub = mumble_env.get_config_public()
    assert pub["host"] == "murmur"
    assert pub["port"] == 64738
    assert pub["password"] == "••••••••"
    # The real password must never leak through the public view.
    assert "R@nger" not in json.dumps(pub)


def test_get_config_public_no_password(mumble_env):
    mumble_env._config = {"host": "murmur", "port": 64738}
    pub = mumble_env.get_config_public()
    assert "password" not in pub or not pub["password"]


def test_save_and_load_config_roundtrip(mumble_env):
    cfg = {
        "host": "192.168.0.240",
        "port": 64738,
        "username": "ArrowBot",
        "password": "",
    }
    mumble_env.save_config(cfg)
    # A fresh read from disk should reproduce the config.
    mumble_env._config = {}
    mumble_env.load_config()
    assert mumble_env._config["host"] == "192.168.0.240"
    assert mumble_env._config["port"] == 64738


def test_clear_config_removes_file(mumble_env):
    from backend.mumble import monitor as mon

    mumble_env.save_config({"host": "h", "port": 64738})
    assert mon.CONFIG_PATH.exists()
    mumble_env.clear_config()
    assert not mon.CONFIG_PATH.exists()
    assert mumble_env._config == {}


def test_apply_config_without_host_does_not_start(mumble_env):
    mumble_env.apply_config({"host": "", "port": 64738})
    assert mumble_env._thread is None
    assert mumble_env.get_status()["connected"] is False


def test_apply_config_with_host_connects(mumble_env):
    mumble_env.apply_config({"host": "murmur", "port": 64738, "username": "ArrowBot"})
    # The mocked Mumble reports ready immediately; the monitor thread should flip to
    # connected within a moment.
    _wait_until(lambda: mumble_env.get_status()["connected"], timeout=3.0)
    assert mumble_env.get_status()["connected"] is True
    mumble_env.stop()
    assert mumble_env.get_status()["connected"] is False


def test_get_status_returns_copy(mumble_env):
    s1 = mumble_env.get_status()
    s1["connected"] = True
    # Mutating the returned dict must not corrupt the monitor's internal state.
    assert mumble_env.get_status()["connected"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 3. REST endpoints (/mumble/*)
# ─────────────────────────────────────────────────────────────────────────────


def test_status_requires_auth(mumble_env, client):
    r = client.get("/mumble/status")
    assert r.status_code in (401, 403)


def test_status_returns_state(mumble_env, client):
    tok = admin_token(client)
    r = client.get("/mumble/status", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"connected", "error", "channels", "users"}
    assert body["connected"] is False  # nothing configured in the test env


def test_config_get_requires_admin_role(mumble_env, client):
    _cs, op_tok, _id = register(client, role="OPERATOR")
    r = client.get("/mumble/config", headers=auth(op_tok))
    assert r.status_code == 403


def test_config_set_get_delete_roundtrip(mumble_env, client):
    tok = admin_token(client)

    r = client.post(
        "/mumble/config",
        headers=auth(tok),
        json={
            "host": "192.168.0.240",
            "port": 64738,
            "username": "ArrowBot",
            "password": "s3cret",
        },
    )
    assert r.status_code == 200 and r.json()["ok"] is True

    r = client.get("/mumble/config", headers=auth(tok))
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["host"] == "192.168.0.240"
    assert cfg["port"] == 64738
    assert cfg["password"] == "••••••••"  # masked, never the real value

    r = client.delete("/mumble/config", headers=auth(tok))
    assert r.status_code == 200
    assert client.get("/mumble/config", headers=auth(tok)).json().get("host") in (
        None,
        "",
    )


def test_ping_not_configured(mumble_env, client):
    tok = admin_token(client)
    r = client.get("/mumble/ping", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "not configured" in body["msg"].lower()


def test_ping_tcp_probe_succeeds(mumble_env, client, monkeypatch):
    # Configure a host directly (no bot thread), then mock the TCP probe.
    mumble_env._config = {"host": "murmur", "port": 64738}

    class _Writer:
        def close(self):
            pass

        async def wait_closed(self):
            return None

    async def _fake_open_connection(host, port):
        assert host == "murmur" and port == 64738
        return object(), _Writer()

    monkeypatch.setattr(asyncio, "open_connection", _fake_open_connection)

    tok = admin_token(client)
    r = client.get("/mumble/ping", headers=auth(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["host"] == "murmur"
    assert body["port"] == 64738
    assert "tcp_ms" in body


def test_ping_tcp_probe_timeout(mumble_env, client, monkeypatch):
    mumble_env._config = {"host": "murmur", "port": 64738}

    async def _hang(host, port):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "open_connection", _hang)

    tok = admin_token(client)
    body = client.get("/mumble/ping", headers=auth(tok)).json()
    assert body["ok"] is False
    assert "timeout" in body["msg"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# 3b. Voice channels — CRUD + access gating
# ─────────────────────────────────────────────────────────────────────────────


def _make_channel(client, tok, **over):
    body = {"name": "Command Net", "mumble_channel": "Command"}
    body.update(over)
    r = client.post("/mumble/channels", headers=auth(tok), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_voice_channel_crud_roundtrip(mumble_env, client):
    tok = admin_token(client)
    ch = _make_channel(client, tok, name="Fires", classification=0)
    cid = ch["id"]
    assert ch["name"] == "Fires"

    listed = client.get("/mumble/channels", headers=auth(tok))
    assert listed.status_code == 200
    assert any(c["id"] == cid for c in listed.json())

    r = client.patch(
        f"/mumble/channels/{cid}", headers=auth(tok), json={"name": "Fires Net"}
    )
    assert r.status_code == 200 and r.json()["name"] == "Fires Net"

    r = client.delete(f"/mumble/channels/{cid}", headers=auth(tok))
    assert r.status_code == 204
    remaining = client.get("/mumble/channels", headers=auth(tok)).json()
    assert all(c["id"] != cid for c in remaining)


def test_voice_channel_write_requires_manager_role(mumble_env, client):
    _cs, op_tok, _id = register(client, role="OPERATOR")
    # GET is open to any operator …
    assert client.get("/mumble/channels", headers=auth(op_tok)).status_code == 200
    # … writes are ADMIN / BATTLE_CAPTAIN only.
    assert (
        client.post(
            "/mumble/channels", headers=auth(op_tok), json={"name": "x"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/mumble/channels/1", headers=auth(op_tok), json={"name": "x"}
        ).status_code
        == 403
    )
    assert client.delete("/mumble/channels/1", headers=auth(op_tok)).status_code == 403


def test_voice_channel_password_never_exposed(mumble_env, client):
    tok = admin_token(client)
    ch = _make_channel(client, tok, name="Secret Net", password="hunter2")
    assert "password" not in ch
    assert ch["has_password"] is True
    listed = client.get("/mumble/channels", headers=auth(tok)).json()
    match = next(c for c in listed if c["id"] == ch["id"])
    assert "password" not in match


def test_voice_channel_clearance_filter(mumble_env, client):
    tok = admin_token(client)
    low = _make_channel(client, tok, name="Open Net", classification=0)
    high = _make_channel(client, tok, name="TS Net", classification=3)
    _cs, op_tok, _id = register(client, role="OPERATOR")  # clearance 0
    visible = {
        c["id"] for c in client.get("/mumble/channels", headers=auth(op_tok)).json()
    }
    assert low["id"] in visible
    assert high["id"] not in visible


def test_voice_channel_min_role_filter(mumble_env, client):
    tok = admin_token(client)
    bc_only = _make_channel(client, tok, name="BC Net", min_role="BATTLE_CAPTAIN")
    _cs, op_tok, _id = register(client, role="OPERATOR")
    visible = {
        c["id"] for c in client.get("/mumble/channels", headers=auth(op_tok)).json()
    }
    assert bc_only["id"] not in visible


def test_voice_channel_mission_scope_filter(mumble_env, client):
    tok = admin_token(client)
    m = client.post("/missions", headers=auth(tok), json={"name": "OP TESTMISSION"})
    assert m.status_code == 201, m.text
    scoped = _make_channel(client, tok, name="Mission Net", mission_id=m.json()["id"])
    _cs, op_tok, _id = register(client, role="OPERATOR")  # no mission assigned
    visible = {
        c["id"] for c in client.get("/mumble/channels", headers=auth(op_tok)).json()
    }
    assert scoped["id"] not in visible


def test_voice_channel_connect_info_returns_credentials(mumble_env, client):
    tok = admin_token(client)
    mumble_env._config = {"host": "murmur", "port": 64738}  # default server
    ch = _make_channel(client, tok, name="Cmd", mumble_channel="Command", password="pw")
    r = client.get(f"/mumble/channels/{ch['id']}/connect", headers=auth(tok))
    assert r.status_code == 200
    info = r.json()
    assert info["host"] == "murmur"  # resolved from default server
    assert info["password"] == "pw"  # revealed to an authorised joiner
    assert info["channel"] == "Command"


def test_voice_channel_connect_denied_by_clearance(mumble_env, client):
    tok = admin_token(client)
    mumble_env._config = {"host": "murmur", "port": 64738}
    high = _make_channel(client, tok, name="TS", classification=3)
    _cs, op_tok, _id = register(client, role="OPERATOR")  # clearance 0
    r = client.get(f"/mumble/channels/{high['id']}/connect", headers=auth(op_tok))
    assert r.status_code == 403


# ─────────────────────────────────────────────────────────────────────────────
# 4. Front desktop audio helpers (no Qt loop, no real device)
# ─────────────────────────────────────────────────────────────────────────────

pytest.importorskip("numpy")
pytest.importorskip("sounddevice")
pytest.importorskip("PyQt6")


def test_audio_out_mixes_queue_into_output_buffer():
    import numpy as np
    from front.mumble.client import _AudioOut, CHUNK_FRAMES

    out = _AudioOut()
    pcm = (np.arange(CHUNK_FRAMES, dtype=np.int16)).tobytes()
    out.push(pcm)

    outdata = np.zeros((CHUNK_FRAMES, 1), dtype=np.int16)
    out._cb(outdata, CHUNK_FRAMES, None, None)

    assert np.array_equal(outdata[:, 0], np.arange(CHUNK_FRAMES, dtype=np.int16))


def test_audio_out_silence_when_queue_empty():
    import numpy as np
    from front.mumble.client import _AudioOut

    out = _AudioOut()
    outdata = np.ones((320, 1), dtype=np.int16)
    out._cb(outdata, 320, None, None)
    assert np.array_equal(outdata[:, 0], np.zeros(320, dtype=np.int16))


def test_audio_out_push_never_raises_when_full():
    from front.mumble.client import _AudioOut

    out = _AudioOut()
    # Queue caps at 100; pushing far past that must not raise (frames are dropped).
    for _ in range(250):
        out.push(b"\x00\x00")


def test_audio_in_gates_on_ptt():
    import numpy as np
    from front.mumble.client import _AudioIn, CHUNK_FRAMES

    received: list[bytes] = []
    ain = _AudioIn(on_chunk=received.append)
    indata = np.ones((CHUNK_FRAMES, 1), dtype=np.int16)

    # Inactive → nothing forwarded.
    ain._cb(indata, CHUNK_FRAMES, None, None)
    assert received == []

    # Active → the mic chunk is forwarded.
    ain.set_active(True)
    ain._cb(indata, CHUNK_FRAMES, None, None)
    assert len(received) == 1
    assert len(received[0]) == CHUNK_FRAMES * 2  # int16 → 2 bytes/sample


def test_list_audio_devices_splits_inputs_and_outputs(monkeypatch):
    from front.mumble import client as cl

    fake = [
        {"name": "Mic A", "max_input_channels": 1, "max_output_channels": 0},
        {"name": "Speaker B", "max_input_channels": 0, "max_output_channels": 2},
        {"name": "Headset C", "max_input_channels": 1, "max_output_channels": 2},
    ]
    monkeypatch.setattr(cl.sd, "query_devices", lambda: fake)

    inputs, outputs = cl.list_audio_devices()
    assert (0, "Mic A") in inputs
    assert (2, "Headset C") in inputs
    assert (1, "Speaker B") in outputs
    assert (2, "Headset C") in outputs
    assert (1, "Speaker B") not in inputs


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _wait_until(pred, timeout=3.0, interval=0.02):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False
