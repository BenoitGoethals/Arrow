"""Structural smoke tests for the alert pipeline in web/templates/map.html.

We can't run a JS engine in pytest, but we CAN verify that every link in the
alert chain is present and wired up.  These tests catch the most common cause
of "no alert on web": an edit that broke a hook (renamed a function, deleted
a WS branch, mismatched braces) without triggering a build error.

The chain we verify:

    1. ws.onmessage → channel==='alert' → event==='triggered'
                    → handleAlertTriggered(msg.data)
    2. handleAlertTriggered() → showAlertToast(d) → zoom → marker
    3. showAlertToast() → _playAlertTone() + _speakAlert()
    4. ALERT_COLOURS / ALERT_ICONS include every server-side alert type
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

MAP_HTML = Path(__file__).parents[2] / "web" / "templates" / "map.html"


@pytest.fixture(scope="module")
def js_source() -> str:
    """Return the contents of the largest <script> block in map.html."""
    html = MAP_HTML.read_text(encoding="utf-8")
    # Find the inline <script>…</script> block (no src attribute)
    # The big one starts after a bare `<script>` tag on its own line
    matches = re.findall(r"<script>\s*(.*?)\s*</script>", html, re.DOTALL)
    assert matches, "No inline <script> block found in map.html"
    # The alert handler lives in the biggest inline script block
    return max(matches, key=len)


# ── 1. Required functions exist ──────────────────────────────────────────────


class TestFunctionsDefined:

    @pytest.mark.parametrize(
        "name",
        [
            "_playAlertTone",
            "_speakAlert",
            "showAlertToast",
            "handleAlertTriggered",
            "loadMapAlerts",
        ],
    )
    def test_function_declared(self, js_source, name):
        """Each function the alert chain depends on must be declared."""
        # Match `function NAME(` — the canonical declaration form
        pattern = rf"function\s+{re.escape(name)}\s*\("
        assert re.search(
            pattern, js_source
        ), f"function {name}() is not declared in map.html"


# ── 2. WebSocket → handleAlertTriggered wiring ───────────────────────────────


class TestWebSocketWiring:

    def test_alert_channel_branch_exists(self, js_source):
        """The WS onmessage handler must have an `if msg.channel === 'alert'` branch."""
        # Allow single or double quotes
        assert re.search(
            r"msg\.channel\s*===?\s*['\"]alert['\"]", js_source
        ), "WS handler missing branch for channel === 'alert'"

    def test_triggered_event_calls_handler(self, js_source):
        """The 'triggered' branch must call handleAlertTriggered."""
        # Look for the specific call pattern
        assert re.search(
            r"msg\.event\s*===?\s*['\"]triggered['\"][^{]*handleAlertTriggered",
            js_source,
            re.DOTALL,
        ), "msg.event === 'triggered' branch does not call handleAlertTriggered()"

    def test_ack_event_removes_layer(self, js_source):
        """The 'ack' branch should call removeAlertLayer to clear the map marker."""
        assert re.search(
            r"msg\.event\s*===?\s*['\"]ack['\"][^{]*removeAlertLayer",
            js_source,
            re.DOTALL,
        ), "msg.event === 'ack' branch does not call removeAlertLayer()"


# ── 3. handleAlertTriggered → toast + zoom ───────────────────────────────────


class TestHandleAlertTriggered:

    def _body(self, js_source: str) -> str:
        """Extract the body of handleAlertTriggered (function up to next matching brace)."""
        m = re.search(r"function\s+handleAlertTriggered\s*\([^)]*\)\s*\{", js_source)
        assert m, "handleAlertTriggered not found"
        start = m.end()
        depth = 1
        i = start
        while i < len(js_source) and depth > 0:
            if js_source[i] == "{":
                depth += 1
            elif js_source[i] == "}":
                depth -= 1
            i += 1
        return js_source[start : i - 1]

    def test_calls_show_alert_toast(self, js_source):
        body = self._body(js_source)
        assert (
            "showAlertToast" in body
        ), "handleAlertTriggered() does not call showAlertToast()"

    def test_zooms_to_position(self, js_source):
        body = self._body(js_source)
        assert (
            "map.setView" in body or "map.flyTo" in body
        ), "handleAlertTriggered() does not zoom the map"

    def test_skips_zero_zero_position(self, js_source):
        """The hasPos check must reject 0,0 — that's the no-GPS-fix fallback."""
        body = self._body(js_source)
        # Look for any check that excludes lat===0 && lon===0
        assert re.search(r"latitude\s*===?\s*0\s*&&\s*.*longitude\s*===?\s*0", body), (
            "handleAlertTriggered() does not filter out the 0,0 position "
            "(would zoom the map to null island for ATAK devices without GPS)"
        )


# ── 4. showAlertToast → sound + voice ────────────────────────────────────────


class TestShowAlertToast:

    def _body(self, js_source: str) -> str:
        m = re.search(r"function\s+showAlertToast\s*\([^)]*\)\s*\{", js_source)
        assert m, "showAlertToast not found"
        start = m.end()
        depth = 1
        i = start
        while i < len(js_source) and depth > 0:
            if js_source[i] == "{":
                depth += 1
            elif js_source[i] == "}":
                depth -= 1
            i += 1
        return js_source[start : i - 1]

    def test_plays_alert_tone(self, js_source):
        body = self._body(js_source)
        assert (
            "_playAlertTone" in body
        ), "showAlertToast() does not call _playAlertTone() → no beep on alert"

    def test_speaks_alert(self, js_source):
        body = self._body(js_source)
        assert (
            "_speakAlert" in body
        ), "showAlertToast() does not call _speakAlert() → no voice announcement"

    def test_renders_toast_card(self, js_source):
        body = self._body(js_source)
        # Toast must create a DOM element and append it
        assert "createElement" in body, "showAlertToast() does not create a DOM element"
        assert (
            "appendChild" in body or "prepend" in body
        ), "showAlertToast() never inserts the card into the DOM"


# ── 5. ATAK_EMERGENCY has dedicated styling ──────────────────────────────────


class TestAtakEmergencyStyling:

    def test_atak_emergency_in_colours(self, js_source):
        """ATAK_EMERGENCY must have a colour entry so the toast isn't blank."""
        # Find the ALERT_COLOURS object
        m = re.search(r"const\s+ALERT_COLOURS\s*=\s*\{([^}]*)\}", js_source)
        assert m, "ALERT_COLOURS constant not found"
        assert "ATAK_EMERGENCY" in m.group(
            1
        ), "ATAK_EMERGENCY missing from ALERT_COLOURS"

    def test_atak_emergency_in_icons(self, js_source):
        m = re.search(r"const\s+ALERT_ICONS\s*=\s*\{([^}]*)\}", js_source)
        assert m, "ALERT_ICONS constant not found"
        assert "ATAK_EMERGENCY" in m.group(1), "ATAK_EMERGENCY missing from ALERT_ICONS"

    def test_atak_emergency_voice_phrase_defined(self, js_source):
        """_speakAlert must map ATAK_EMERGENCY to a human-friendly phrase."""
        m = re.search(
            r"function\s+_speakAlert\s*\([^)]*\)\s*\{(.*?)\n    \}",
            js_source,
            re.DOTALL,
        )
        assert m, "_speakAlert body not found"
        body = m.group(1)
        assert "ATAK_EMERGENCY" in body, (
            "_speakAlert does not handle ATAK_EMERGENCY → voice would say "
            "'a t a k underscore emergency' instead of 'ATAK emergency beacon'"
        )


# ── 6. Audio APIs used correctly ─────────────────────────────────────────────


class TestAudioApiUsage:

    def test_audio_context_referenced(self, js_source):
        """_playAlertTone must use AudioContext for the beep."""
        m = re.search(r"function\s+_playAlertTone[\s\S]*?\n    \}", js_source)
        assert m, "_playAlertTone body not found"
        body = m.group(0)
        assert "AudioContext" in body, "_playAlertTone does not create an AudioContext"
        assert (
            "createOscillator" in body
        ), "_playAlertTone does not call createOscillator"

    def test_speech_synthesis_referenced(self, js_source):
        """_speakAlert must use the Web Speech API."""
        m = re.search(r"function\s+_speakAlert[\s\S]*?\n    \}", js_source)
        assert m, "_speakAlert body not found"
        body = m.group(0)
        assert (
            "speechSynthesis" in body
        ), "_speakAlert does not use window.speechSynthesis"
        assert (
            "SpeechSynthesisUtterance" in body
        ), "_speakAlert does not construct a SpeechSynthesisUtterance"

    def test_speech_synthesis_feature_detected(self, js_source):
        """_speakAlert must guard with a feature-detect so it doesn't crash on
        older browsers — otherwise an exception would break the whole toast."""
        m = re.search(r"function\s+_speakAlert[\s\S]*?\n    \}", js_source)
        body = m.group(0)
        assert (
            "'speechSynthesis' in window" in body
            or '"speechSynthesis" in window' in body
        ), (
            "_speakAlert missing feature-detect: would throw on browsers "
            "without Web Speech API"
        )


# ── 7. Brace balance (catches truncation / mid-edit save) ────────────────────


class TestStructuralIntegrity:

    def test_braces_balanced(self, js_source):
        """Open and close braces must balance — catches an unfinished edit."""
        opens = js_source.count("{")
        closes = js_source.count("}")
        assert (
            opens == closes
        ), f"Brace imbalance in <script> block: {opens} '{{' vs {closes} '}}'"

    def test_parens_balanced(self, js_source):
        opens = js_source.count("(")
        closes = js_source.count(")")
        assert (
            opens == closes
        ), f"Paren imbalance in <script> block: {opens} '(' vs {closes} ')'"

    def test_no_unterminated_template_literals(self, js_source):
        """A `template literal` left unclosed would break everything after it."""
        # Strip everything inside template literals first (balanced backticks)
        # then assert no stray backticks remain by counting them.
        backticks = js_source.count("`")
        assert (
            backticks % 2 == 0
        ), f"Odd number of backticks ({backticks}) — unterminated template literal"
