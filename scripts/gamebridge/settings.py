"""
Persistent settings for the GameBridge Python client.

Settings are stored in ~/.gamebridge/settings.json.
All callers should use load() / save() rather than reading the file directly.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_SETTINGS_PATH = Path.home() / ".gamebridge" / "settings.json"

_DEFAULTS: dict[str, Any] = {
    "window_name": "RuneLite",
    "port": 7070,
    "host": "127.0.0.1",
    "hull_y_offset": 0,
}


def load() -> dict[str, Any]:
    """Return settings dict, falling back to defaults for missing keys."""
    settings = dict(_DEFAULTS)
    if _SETTINGS_PATH.exists():
        try:
            with _SETTINGS_PATH.open("r", encoding="utf-8") as f:
                stored = json.load(f)
            settings.update(stored)
        except Exception as exc:
            log.warning("Could not read settings from %s: %s", _SETTINGS_PATH, exc)
    return settings


def save(settings: dict[str, Any]) -> None:
    """Persist settings dict to disk."""
    try:
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except Exception as exc:
        log.warning("Could not save settings to %s: %s", _SETTINGS_PATH, exc)


def get(key: str) -> Any:
    """Read a single setting by key."""
    return load().get(key, _DEFAULTS.get(key))


def set(key: str, value: Any) -> None:
    """Update a single setting and persist."""
    settings = load()
    settings[key] = value
    save(settings)
