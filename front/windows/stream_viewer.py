"""Stream Viewer Window — renders Android WS, MJPEG, HLS, and recordings."""
from __future__ import annotations
import json
from typing import Optional

from PyQt6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QKeySequence, QShortcut


# ── Viewer HTML ────────────────────────────────────────────────────────────────

def _build_html(cfg: dict) -> str:
    """Return a complete HTML page for the given stream config dict."""
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Stream</title>
<script src="https://cdn.jsdelivr.net/npm/hls.js@latest/dist/hls.min.js"></script>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html,body {{ background:#000; width:100%; height:100%; overflow:hidden;
             font-family:'Courier New',monospace; color:#c9d1d9; }}
#wrap {{ width:100vw; height:100vh; display:flex; flex-direction:column; }}
#bar  {{ display:flex; align-items:center; gap:10px; padding:5px 12px;
         background:rgba(13,17,23,.92); border-bottom:1px solid #21262d;
         flex-shrink:0; font-size:11px; }}
#bar .call  {{ color:#3fb950; font-weight:700; font-size:12px; }}
#bar .fps   {{ color:#484f58; }}
#bar .status{{ color:#d29922; }}
#bar .spacer{{ flex:1; }}
#view {{ flex:1; display:flex; align-items:center; justify-content:center;
         background:#000; overflow:hidden; }}
#ws-img  {{ max-width:100%; max-height:100%; object-fit:contain; display:none; }}
#hls-vid {{ max-width:100%; max-height:100%; display:none; background:#000; }}
#msg     {{ color:#484f58; font-size:12px; }}
</style>
</head>
<body>
<div id="wrap">
  <div id="bar">
    <span class="call" id="bar-call">—</span>
    <span class="status" id="bar-status">Connecting…</span>
    <span class="fps" id="bar-fps"></span>
    <span class="spacer"></span>
    <span id="bar-type" style="color:#30363d;font-size:10px;"></span>
  </div>
  <div id="view">
    <img id="ws-img" alt="stream">
    <video id="hls-vid" autoplay muted playsinline controls></video>
    <div id="msg">Initialising…</div>
  </div>
</div>
<script>
'use strict';
const CFG    = {cfg_json};
const wsImg  = document.getElementById('ws-img');
const hlsVid = document.getElementById('hls-vid');
const msg    = document.getElementById('msg');
const barCall   = document.getElementById('bar-call');
const barStatus = document.getElementById('bar-status');
const barFps    = document.getElementById('bar-fps');
const barType   = document.getElementById('bar-type');

barCall.textContent = CFG.callsign || CFG.name || '—';
barType.textContent = CFG.type.toUpperCase();

// ── Helpers ───────────────────────────────────────────────────────────────────
function showImg(src) {{
  msg.style.display = 'none';
  hlsVid.style.display = 'none';
  wsImg.style.display = 'block';
  wsImg.src = src;
}}
function showVideo() {{
  msg.style.display = 'none';
  wsImg.style.display = 'none';
  hlsVid.style.display = 'block';
}}
function showMsg(text, color) {{
  wsImg.style.display = 'none';
  hlsVid.style.display = 'none';
  msg.style.display = 'block';
  msg.style.color = color || '#484f58';
  msg.textContent = text;
}}

// ── Android / WebSocket JPEG stream ──────────────────────────────────────────
function connectWS(wsUrl) {{
  barType.textContent = 'ANDROID LIVE';
  let frames = 0, lastT = Date.now(), prevSrc = null;
  const ws = new WebSocket(wsUrl);
  ws.binaryType = 'arraybuffer';

  ws.onopen  = () => {{ barStatus.textContent = '● LIVE'; barStatus.style.color = '#3fb950'; }};
  ws.onclose = () => {{
    barStatus.textContent = '○ DISCONNECTED'; barStatus.style.color = '#f85149';
    showMsg('Stream ended', '#f85149');
    setTimeout(() => connectWS(wsUrl), 3000);
  }};
  ws.onerror = () => {{ barStatus.textContent = 'ERROR'; barStatus.style.color = '#f85149'; }};
  ws.onmessage = ev => {{
    if (typeof ev.data === 'string') {{
      try {{ const j = JSON.parse(ev.data); if (j.event === 'ended') ws.close(); }} catch(_) {{}}
      return;
    }}
    const blob = new Blob([ev.data], {{ type:'image/jpeg' }});
    const url  = URL.createObjectURL(blob);
    showImg(url);
    if (prevSrc && prevSrc.startsWith('blob:')) URL.revokeObjectURL(prevSrc);
    prevSrc = url;
    frames++;
    const now = Date.now();
    if (now - lastT >= 1000) {{
      barFps.textContent = frames + ' fps';
      frames = 0; lastT = now;
    }}
  }};
}}

// ── MJPEG stream (via img src — browser handles multipart) ───────────────────
function playMJPEG(url, authHeader) {{
  barType.textContent = 'MJPEG';
  barStatus.textContent = '● CONNECTING';
  // If URL needs auth, we must fetch with headers and build blob stream
  if (authHeader) {{
    playMJPEGWithAuth(url, authHeader);
  }} else {{
    showImg(url);
    wsImg.onload  = () => {{ barStatus.textContent='● LIVE'; barStatus.style.color='#3fb950'; }};
    wsImg.onerror = () => {{ barStatus.textContent='ERROR'; barStatus.style.color='#f85149'; }};
  }}
}}

// Authenticated MJPEG (recording playback) — manual boundary parsing
async function playMJPEGWithAuth(url, authHeader) {{
  barStatus.textContent = '⟳ LOADING';
  try {{
    const resp = await fetch(url, {{ headers: {{ Authorization: authHeader }} }});
    if (!resp.ok) {{ showMsg('HTTP ' + resp.status, '#f85149'); return; }}
    barStatus.textContent = '● PLAYING'; barStatus.style.color = '#3fb950';
    const reader = resp.body.getReader();
    let buf = new Uint8Array(0);
    const SOI = [0xFF,0xD8], EOI = [0xFF,0xD9];
    function concat(a, b) {{
      const c = new Uint8Array(a.length + b.length);
      c.set(a); c.set(b, a.length); return c;
    }}
    while (true) {{
      const {{ done, value }} = await reader.read();
      if (done) break;
      buf = concat(buf, value);
      let start = -1;
      for (let i=0; i < buf.length-1; i++) {{
        if (buf[i]===0xFF && buf[i+1]===0xD8) {{ start=i; break; }}
      }}
      let end = -1;
      for (let i=start+1; i < buf.length-1; i++) {{
        if (buf[i]===0xFF && buf[i+1]===0xD9) {{ end=i+2; break; }}
      }}
      if (start >= 0 && end > start) {{
        const frame = buf.slice(start, end);
        buf = buf.slice(end);
        const blob = new Blob([frame], {{ type:'image/jpeg' }});
        const url2 = URL.createObjectURL(blob);
        showImg(url2);
        URL.revokeObjectURL(wsImg.dataset.prev || '');
        wsImg.dataset.prev = url2;
      }}
    }}
  }} catch(e) {{ showMsg('Error: ' + e.message, '#f85149'); }}
}}

// ── HLS stream (Octopus / external HLS) ──────────────────────────────────────
function playHLS(url) {{
  barType.textContent = 'HLS';
  showVideo();
  if (Hls.isSupported()) {{
    const hls = new Hls({{ enableWorker: false }});
    hls.loadSource(url);
    hls.attachMedia(hlsVid);
    hls.on(Hls.Events.MANIFEST_PARSED, () => {{
      hlsVid.play().catch(()=> {{}});
      barStatus.textContent = '● LIVE'; barStatus.style.color='#3fb950';
    }});
    hls.on(Hls.Events.ERROR, (_,d) => {{
      if (d.fatal) {{ barStatus.textContent = 'ERROR'; barStatus.style.color='#f85149'; }}
    }});
  }} else if (hlsVid.canPlayType('application/vnd.apple.mpegurl')) {{
    hlsVid.src = url;
    hlsVid.play().catch(()=>{{}});
    barStatus.textContent = '● LIVE'; barStatus.style.color='#3fb950';
  }} else {{
    showMsg('HLS not supported in this browser', '#f85149');
  }}
}}

// ── Generic video ─────────────────────────────────────────────────────────────
function playVideo(url) {{
  barType.textContent = 'VIDEO';
  showVideo();
  hlsVid.src = url;
  hlsVid.play().catch(()=>{{}});
  barStatus.textContent = '● PLAYING'; barStatus.style.color='#3fb950';
}}

// ── Router ────────────────────────────────────────────────────────────────────
(function route() {{
  const t = (CFG.type || '').toLowerCase();
  if (t === 'ws_jpeg' || t === 'android' || t === 'live') {{
    connectWS(CFG.ws_url);
  }} else if (t === 'hls') {{
    playHLS(CFG.url);
  }} else if (t === 'mjpeg') {{
    playMJPEG(CFG.url, CFG.auth_header);
  }} else if (t === 'recording') {{
    playMJPEGWithAuth(CFG.url, CFG.auth_header);
  }} else if (t === 'video') {{
    playVideo(CFG.url);
  }} else {{
    showMsg('Unknown stream type: ' + CFG.type, '#f85149');
  }}
}})();
</script>
</body>
</html>"""


# ── Viewer Window ──────────────────────────────────────────────────────────────

class StreamViewerWindow(QMainWindow):
    """Opens a stream in a QWebEngineView-backed window."""

    def __init__(self, cfg: dict, backend_url: str, parent=None):
        super().__init__(parent)
        self._cfg     = cfg
        self._backend = backend_url.rstrip("/")

        title = cfg.get("callsign") or cfg.get("name") or "Stream"
        self.setWindowTitle(f"📡  {title}")
        self.resize(720, 480)
        self.setMinimumSize(320, 240)

        # Allow cross-origin WebSocket & fetch from local/remote HTML
        view = QWebEngineView(self)
        s = view.page().settings()
        s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        s.setAttribute(QWebEngineSettings.WebAttribute.AutoLoadImages, True)

        html = _build_html(cfg)
        # Use backend URL as base so relative WS/fetch calls resolve to it
        view.page().setHtml(html, QUrl(self._backend + "/"))

        self.setCentralWidget(view)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self.close)

    @classmethod
    def open_android(cls, stream: dict, backend_url: str, token: str,
                     parent=None) -> "StreamViewerWindow":
        ws_base = backend_url.replace("http://", "ws://").replace("https://", "wss://")
        sid = stream.get("id", "")
        cfg = {
            "type":      "ws_jpeg",
            "callsign":  stream.get("callsign", sid),
            "ws_url":    f"{ws_base}/streams/{sid}/consume?token={token}",
        }
        return cls(cfg, backend_url, parent)

    @classmethod
    def open_external(cls, stream: dict, backend_url: str, token: str,
                      parent=None) -> "StreamViewerWindow":
        stype = (stream.get("stream_type") or "video").lower()
        url   = stream.get("url", "")
        if stype in ("hls",):
            t = "hls"
        elif stype in ("mjpeg", "motion-jpeg"):
            t = "mjpeg"
        else:
            t = "video"
        cfg = {
            "type": t,
            "name": stream.get("name", "External stream"),
            "url":  url,
        }
        return cls(cfg, backend_url, parent)

    @classmethod
    def open_octopus(cls, stream: dict, backend_url: str, token: str,
                     parent=None) -> "StreamViewerWindow":
        # Octopus streams are typically HLS — route via Arrow's /octopus/hls/ proxy
        stream_id = stream.get("id") or stream.get("stream_id", "")
        # Try to get HLS URL from stream object, else build proxy URL
        hls_url = stream.get("hls_url") or stream.get("url") or ""
        if not hls_url and stream_id:
            hls_url = f"{backend_url}/octopus/hls/{stream_id}/index.m3u8"
        cfg = {
            "type": "hls",
            "name": stream.get("name") or stream.get("callsign") or stream_id,
            "url":  hls_url,
        }
        return cls(cfg, backend_url, parent)

    @classmethod
    def open_recording(cls, rec: dict, backend_url: str, token: str,
                       parent=None) -> "StreamViewerWindow":
        rec_id = rec.get("id", "")
        cfg = {
            "type":        "recording",
            "callsign":    f"REC — {rec.get('callsign', rec_id)}",
            "url":         f"{backend_url}/streams/recordings/{rec_id}/playback",
            "auth_header": f"Bearer {token}",
        }
        return cls(cfg, backend_url, parent)
