"""JWT credential storage — uses keyring when available, falls back to memory."""

from typing import Optional
import keyring

_SERVICE = "ArrowFront"


def save_token(server_url: str, token: str) -> None:
    try:
        keyring.set_password(_SERVICE, server_url, token)
    except Exception:
        pass  # keyring unavailable — token lives only in memory


def load_token(server_url: str) -> Optional[str]:
    try:
        return keyring.get_password(_SERVICE, server_url)
    except Exception:
        return None


def clear_token(server_url: str) -> None:
    try:
        keyring.delete_password(_SERVICE, server_url)
    except Exception:
        pass
