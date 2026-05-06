"""Launch the Arrow backend (FastAPI :6001) and web dashboard (Flask :6000) together.

Usage:
    uv run python run.py
    # or
    uv run arrow
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import sys
import time


def _run_backend() -> None:
    import uvicorn

    from backend.config.xml_config import load_config

    cfg = load_config()
    uvicorn.run(
        "backend.main:app",
        host=cfg.server.host,
        port=cfg.server.port,
        reload=False,
        log_level="info",
    )


def _run_web() -> None:
    os.environ.setdefault("ARROW_BACKEND_URL", "http://localhost:6001")
    from web.app import app

    app.run(host="0.0.0.0", port=6002, debug=False, use_reloader=False)


def main() -> int:
    mp.set_start_method("spawn", force=True)
    backend = mp.Process(target=_run_backend, name="arrow-backend")
    web = mp.Process(target=_run_web, name="arrow-web")

    backend.start()
    web.start()
    print(f"[arrow] backend pid={backend.pid} on http://localhost:6001 (docs: /docs)")
    print(f"[arrow] web     pid={web.pid} on http://localhost:6002")

    def _shutdown(signum, frame) -> None:  # noqa: ARG001
        print("\n[arrow] shutting down…")
        for p in (web, backend):
            if p.is_alive():
                p.terminate()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        while backend.is_alive() and web.is_alive():
            time.sleep(0.5)
    finally:
        for p in (web, backend):
            if p.is_alive():
                p.terminate()
            p.join(timeout=5)

    return 0 if backend.exitcode == 0 and web.exitcode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
