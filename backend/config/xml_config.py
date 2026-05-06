from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.xml"


@dataclass(slots=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 6001


@dataclass(slots=True)
class DatabaseConfig:
    url: str = "sqlite:///./arrow.db"


@dataclass(slots=True)
class AuthConfig:
    secret: str = "change-me-in-production"
    algorithm: str = "HS256"
    token_expire_minutes: int = 1440


@dataclass(slots=True)
class OperatorConfig:
    callsign: str = "ALPHA-1"
    team: str = "Alpha"


@dataclass(slots=True)
class MapsConfig:
    offline: bool = True


@dataclass(slots=True)
class CotConfig:
    multicast_group: str = "239.2.3.1"
    port: int = 6969


@dataclass(slots=True)
class AppConfig:
    server: ServerConfig
    database: DatabaseConfig
    auth: AuthConfig
    operator: OperatorConfig
    maps: MapsConfig
    cot: CotConfig


def _text(root, xpath: str, default: str) -> str:
    el = root.find(xpath)
    return el.text.strip() if el is not None and el.text else default


def load_config(path: Path | str | None = None) -> AppConfig:
    """Parse the XML config from disk, falling back to defaults if absent."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return AppConfig(
            server=ServerConfig(),
            database=DatabaseConfig(),
            auth=AuthConfig(),
            operator=OperatorConfig(),
            maps=MapsConfig(),
            cot=CotConfig(),
        )

    tree = etree.parse(str(p))
    root = tree.getroot()

    return AppConfig(
        server=ServerConfig(
            host=_text(root, "server/host", "0.0.0.0"),
            port=int(_text(root, "server/port", "6001")),
        ),
        database=DatabaseConfig(
            url=_text(root, "database/url", "sqlite:///./arrow.db"),
        ),
        auth=AuthConfig(
            secret=_text(root, "auth/secret", "change-me-in-production"),
            algorithm=_text(root, "auth/algorithm", "HS256"),
            token_expire_minutes=int(_text(root, "auth/token_expire_minutes", "1440")),
        ),
        operator=OperatorConfig(
            callsign=_text(root, "operator/callsign", "ALPHA-1"),
            team=_text(root, "operator/team", "Alpha"),
        ),
        maps=MapsConfig(
            offline=_text(root, "maps/offline", "true").lower() == "true",
        ),
        cot=CotConfig(
            multicast_group=_text(root, "cot/multicast_group", "239.2.3.1"),
            port=int(_text(root, "cot/port", "6969")),
        ),
    )
