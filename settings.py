"""User preferences (timezone, auto-refresh) persisted to settings.json next to the app."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover — Python 3.8 fallback
    ZoneInfo = None  # type: ignore[assignment]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment]

DEFAULTS: dict[str, Any] = {
    "timezone": "system",
    "auto_refresh": True,
    "last_seen_version": "",
    "ai_base_url": "http://10.0.0.54:11434",
    "ai_model": "qwen2.5:7b",
    "ai_api_key": "",        # password/token for a reverse-proxied server (blank = none)
    "ai_verify_ssl": True,   # turn off only for a self-signed HTTPS cert
    "user_name": "",         # active user profile name (blank = no personalization)
}

# Preset names offered in the profile dropdown (users can also type their own).
PRESET_USERS = ["Cherry", "Logan", "BJ"]

# (display name, IANA id). "system" → local time from datetime.astimezone().
TIMEZONE_CHOICES: list[tuple[str, str]] = [
    ("System Default", "system"),
    ("Eastern (New York)", "America/New_York"),
    ("Central (Chicago)", "America/Chicago"),
    ("Mountain (Denver)", "America/Denver"),
    ("Mountain (Phoenix, no DST)", "America/Phoenix"),
    ("Pacific (Los Angeles)", "America/Los_Angeles"),
    ("Alaska (Anchorage)", "America/Anchorage"),
    ("Hawaii (Honolulu)", "Pacific/Honolulu"),
    ("UK (London)", "Europe/London"),
    ("Central Europe (Berlin)", "Europe/Berlin"),
    ("Japan (Tokyo)", "Asia/Tokyo"),
    ("UTC", "UTC"),
]


def _settings_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    return base / "settings.json"


_cache: dict[str, Any] | None = None


def load() -> dict[str, Any]:
    """Load settings.json, falling back to defaults for any missing keys."""
    global _cache
    if _cache is not None:
        return _cache
    path = _settings_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError):
            data = {}
    merged = {**DEFAULTS, **data}
    _cache = merged
    return merged


def save(values: dict[str, Any]) -> None:
    """Merge values into settings, write to disk, and refresh the in-memory cache."""
    global _cache
    current = load()
    current.update(values)
    path = _settings_path()
    try:
        path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    except OSError:
        pass
    _cache = current


def get(key: str) -> Any:
    return load().get(key, DEFAULTS.get(key))


def display_label_for(tz_id: str) -> str:
    for label, value in TIMEZONE_CHOICES:
        if value == tz_id:
            return label
    return tz_id


def tz_id_for_label(label: str) -> str:
    for lbl, value in TIMEZONE_CHOICES:
        if lbl == label:
            return value
    return "system"


def _resolve_zone():
    """Return a tzinfo for the configured timezone, or None for 'system'."""
    tz_id = get("timezone") or "system"
    if tz_id == "system":
        return None
    if ZoneInfo is None:
        return None
    try:
        return ZoneInfo(tz_id)
    except ZoneInfoNotFoundError:
        return None


def format_game_time(iso_utc: str | None) -> str:
    """Convert an MLB ISO UTC timestamp into a short local time string per the
    user's timezone setting. Returns '' for None input or 'TBD' for missing time."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
    except ValueError:
        return iso_utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    zone = _resolve_zone()
    local = dt.astimezone() if zone is None else dt.astimezone(zone)
    return local.strftime("%I:%M %p").lstrip("0")


def current_zone_label() -> str:
    """Short label of the active timezone for showing in the UI."""
    tz_id = get("timezone") or "system"
    if tz_id == "system":
        # Try to print the local zone offset, e.g. "Local (UTC-04:00)"
        now = datetime.now().astimezone()
        offset = now.utcoffset()
        if offset is None:
            return "Local time"
        total = int(offset.total_seconds())
        sign = "+" if total >= 0 else "-"
        h, m = divmod(abs(total) // 60, 60)
        return f"Local (UTC{sign}{h:02d}:{m:02d})"
    return display_label_for(tz_id)


# ---------------------------------------------------------------------------
# Per-user profiles (name + interests + saved chat history)
# Stored in profiles.json next to settings.json so the AI can greet each
# person and continue their previous conversation.
# ---------------------------------------------------------------------------

_profiles_cache: dict[str, Any] | None = None


def _profiles_path() -> Path:
    return _settings_path().parent / "profiles.json"


def _load_profiles() -> dict[str, Any]:
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache
    path = _profiles_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (json.JSONDecodeError, OSError):
            data = {}
    _profiles_cache = data
    return data


def _save_profiles(data: dict[str, Any]) -> None:
    global _profiles_cache
    _profiles_cache = data
    try:
        _profiles_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _profile(name: str) -> dict[str, Any]:
    return _load_profiles().get(name) or {"interests": "", "history": []}


def known_user_names() -> list[str]:
    """Preset names plus any custom names that already have a saved profile."""
    names = list(PRESET_USERS)
    for n in _load_profiles().keys():
        if n and n not in names:
            names.append(n)
    return names


def get_interests(name: str) -> str:
    if not name:
        return ""
    return _profile(name).get("interests") or ""


def set_interests(name: str, text: str) -> None:
    if not name:
        return
    profs = _load_profiles()
    prof = profs.get(name) or {"interests": "", "history": []}
    prof["interests"] = text
    profs[name] = prof
    _save_profiles(profs)


def load_history(name: str) -> list[dict[str, str]]:
    if not name:
        return []
    return list(_profile(name).get("history") or [])


def save_history(name: str, messages: list[dict[str, str]], cap: int = 40) -> None:
    """Persist the most recent `cap` messages for a user."""
    if not name:
        return
    profs = _load_profiles()
    prof = profs.get(name) or {"interests": "", "history": []}
    prof["history"] = list(messages)[-cap:]
    profs[name] = prof
    _save_profiles(profs)


def clear_history(name: str) -> None:
    if not name:
        return
    profs = _load_profiles()
    if name in profs:
        profs[name]["history"] = []
        _save_profiles(profs)
