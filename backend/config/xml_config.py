from __future__ import annotations

import os
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
    url: str = "postgresql+psycopg://arrow:arrow_dev@localhost:5432/arrow"


@dataclass(slots=True)
class AuthConfig:
    secret: str = "change-me-in-production"
    algorithm: str = "HS256"
    token_expire_minutes: int = 60


@dataclass(slots=True)
class OperatorConfig:
    callsign: str = "ALPHA-1"
    team: str = "Alpha"


@dataclass(slots=True)
class MapsConfig:
    offline: bool = True
    owm_api_key: str = ""  # OpenWeatherMap API key — optional, enables weather layers


@dataclass(slots=True)
class CotConfig:
    multicast_group: str = "239.2.3.1"
    port: int = 6969


@dataclass(slots=True)
class OctopusConfig:
    url: str = ""  # e.g. http://192.168.0.240:8080
    api_key: str = ""  # override with ARROW_OCTOPUS_API_KEY env var


@dataclass(slots=True)
class AppConfig:
    server: ServerConfig
    database: DatabaseConfig
    auth: AuthConfig
    operator: OperatorConfig
    maps: MapsConfig
    cot: CotConfig
    octopus: OctopusConfig = None  # type: ignore[assignment]


def _text(root, xpath: str, default: str) -> str:
    el = root.find(xpath)
    return el.text.strip() if el is not None and el.text else default


def load_config(path: Path | str | None = None) -> AppConfig:
    """Parse the XML config from disk, falling back to defaults if absent."""
    p = Path(path) if path else CONFIG_PATH
    if not p.exists():
        return AppConfig(
            server=ServerConfig(),
            database=DatabaseConfig(
                url=os.environ.get(
                    "ARROW_DATABASE_URL",
                    "postgresql+psycopg://arrow:arrow_dev@localhost:5432/arrow",
                ),
            ),
            auth=AuthConfig(),
            operator=OperatorConfig(),
            maps=MapsConfig(owm_api_key=os.environ.get("ARROW_OWM_API_KEY", "")),
            cot=CotConfig(),
            octopus=OctopusConfig(
                api_key=os.environ.get("ARROW_OCTOPUS_API_KEY", ""),
            ),
        )

    tree = etree.parse(str(p))
    root = tree.getroot()

    return AppConfig(
        server=ServerConfig(
            host=_text(root, "server/host", "0.0.0.0"),
            port=int(_text(root, "server/port", "6001")),
        ),
        database=DatabaseConfig(
            # Env var wins so Docker can point at the persisted /app/data path
            # without forcing local-dev to change config.xml.
            url=os.environ.get("ARROW_DATABASE_URL")
            or _text(
                root,
                "database/url",
                "postgresql+psycopg://arrow:arrow_dev@localhost:5432/arrow",
            ),
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
            owm_api_key=os.environ.get("ARROW_OWM_API_KEY")
            or _text(root, "openweathermap/api_key", ""),
        ),
        cot=CotConfig(
            multicast_group=_text(root, "cot/multicast_group", "239.2.3.1"),
            port=int(_text(root, "cot/port", "6969")),
        ),
        octopus=OctopusConfig(
            url=_text(root, "octopus/url", ""),
            api_key=os.environ.get("ARROW_OCTOPUS_API_KEY")
            or _text(root, "octopus/api_key", ""),
        ),
    )
