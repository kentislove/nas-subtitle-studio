from __future__ import annotations

import json
from pathlib import Path

from app.config import settings

SETTINGS_PATH = settings.app_data_dir / "studio_settings.json"


def _load() -> dict[str, str]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, str]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)


def get_gemini_api_key() -> str:
    data = _load()
    return str(data.get("gemini_api_key") or settings.gemini_api_key or "").strip()


def is_gemini_configured() -> bool:
    return bool(get_gemini_api_key())


def save_gemini_api_key(api_key: str) -> None:
    data = _load()
    cleaned = api_key.strip()
    if cleaned:
        data["gemini_api_key"] = cleaned
    else:
        data.pop("gemini_api_key", None)
    _save(data)
