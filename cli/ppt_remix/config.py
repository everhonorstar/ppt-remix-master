from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProviderConfig:
    provider: str = "local_mock"
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    model: str = ""
    timeout: int = 120
    retry: int = 2
    extra_options: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemixConfig:
    vision_provider: ProviderConfig = field(default_factory=ProviderConfig)
    image_provider: ProviderConfig = field(default_factory=ProviderConfig)
    text_provider: ProviderConfig = field(default_factory=ProviderConfig)
    skip_small_images: bool = True
    min_image_width: int = 64
    min_image_height: int = 64
    text_length_tolerance: float = 0.15


def _provider_from_dict(value: dict[str, Any] | None) -> ProviderConfig:
    if not value:
        return ProviderConfig()
    known = {key: value[key] for key in ProviderConfig.__dataclass_fields__ if key in value}
    return ProviderConfig(**known)


def load_config(config_path: Path | None) -> RemixConfig:
    if not config_path:
        return RemixConfig()
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return RemixConfig(
        vision_provider=_provider_from_dict(data.get("vision_provider")),
        image_provider=_provider_from_dict(data.get("image_provider")),
        text_provider=_provider_from_dict(data.get("text_provider")),
        skip_small_images=bool(data.get("skip_small_images", True)),
        min_image_width=int(data.get("min_image_width", 64)),
        min_image_height=int(data.get("min_image_height", 64)),
        text_length_tolerance=float(data.get("text_length_tolerance", 0.15)),
    )


def load_dotenv(env_path: Path | None, override: bool = False) -> Path | None:
    path = env_path or find_default_env()
    if not path or not path.exists():
        return None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _clean_env_value(value.strip())
        if key and (override or key not in os.environ):
            os.environ[key] = value
    return path


def find_default_env() -> Path | None:
    candidates = [
        Path.cwd() / ".env",
        Path.cwd().parent / ".env",
        Path("/Users/honor/ppt-remix-master/.env"),
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _clean_env_value(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value
