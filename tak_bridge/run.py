"""Entry point for the TAK bridge service."""

import uvicorn


def main() -> None:
    uvicorn.run(
        "tak_bridge.main:app",
        host="0.0.0.0",
        port=8099,
        log_level="info",
    )


if __name__ == "__main__":
    main()
