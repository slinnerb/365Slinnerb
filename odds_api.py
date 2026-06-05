"""Live sports odds via The Odds API (the-odds-api.com).

Read-only: this only *reads* bookmaker odds to help spot value. It never places
bets. Needs a free API key (set in Settings). Free tier = 500 requests/month, so
results are cached in memory and only refreshed on demand.
"""

from __future__ import annotations

from typing import Any

import requests

import settings as user_settings

BASE = "https://api.the-odds-api.com/v4"
REGIONS = ["us", "uk", "eu", "au"]


def get_key() -> str:
    return (user_settings.get("odds_api_key") or "").strip()


def get_region() -> str:
    r = (user_settings.get("odds_region") or "us").strip().lower()
    return r if r in REGIONS else "us"


def american_implied_prob(odds: Any) -> float | None:
    """Break-even win probability implied by American odds (ignores the vig)."""
    try:
        o = float(str(odds).replace("+", "").strip())
    except (ValueError, TypeError):
        return None
    if o == 0:
        return None
    return 100.0 / (o + 100.0) if o > 0 else abs(o) / (abs(o) + 100.0)


def fmt_american(odds: Any) -> str:
    try:
        o = int(float(odds))
    except (ValueError, TypeError):
        return str(odds)
    return f"+{o}" if o > 0 else str(o)


_cache: dict[str, Any] = {"games": None, "remaining": None, "region": None}


def get_mlb_odds(force: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return (games, meta). Cached in memory; only calls the API when forced,
    when nothing is cached, or when the region changed."""
    region = get_region()
    if _cache["games"] is not None and not force and _cache["region"] == region:
        return _cache["games"], {"remaining": _cache["remaining"], "cached": True, "error": None}

    key = get_key()
    if not key:
        return [], {"error": "no_key"}

    try:
        r = requests.get(
            f"{BASE}/sports/baseball_mlb/odds/",
            params={"apiKey": key, "regions": region, "markets": "h2h", "oddsFormat": "american"},
            timeout=15,
        )
    except Exception as e:
        return [], {"error": f"Couldn't reach the odds service: {e}"}

    if r.status_code == 401:
        return [], {"error": "Odds API key was rejected (401). Check it in Settings."}
    if r.status_code == 429:
        return [], {"error": "Odds API monthly limit reached (429). Try again next month or use a new key."}
    if r.status_code != 200:
        return [], {"error": f"Odds service error HTTP {r.status_code}: {r.text[:150]}"}

    remaining = r.headers.get("x-requests-remaining")
    games: list[dict[str, Any]] = []
    for g in r.json():
        # For each team, find the best (highest-paying) moneyline across books.
        best: dict[str, dict[str, Any]] = {}
        all_books: dict[str, dict[str, Any]] = {}
        for bk in g.get("bookmakers", []):
            title = bk.get("title", bk.get("key", "?"))
            for m in bk.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                for o in m.get("outcomes", []):
                    nm, price = o.get("name"), o.get("price")
                    if nm is None or price is None:
                        continue
                    ip = american_implied_prob(price)
                    all_books.setdefault(nm, {})[title] = price
                    cur = best.get(nm)
                    if cur is None or (ip is not None and ip < cur["implied"]):
                        best[nm] = {"price": price, "book": title, "implied": ip}
        games.append({
            "id": g.get("id"),
            "home": g.get("home_team", ""),
            "away": g.get("away_team", ""),
            "commence": g.get("commence_time"),
            "best": best,
            "all_books": all_books,
            "num_books": len(g.get("bookmakers", [])),
        })

    _cache.update({"games": games, "remaining": remaining, "region": region})
    return games, {"remaining": remaining, "cached": False, "error": None}
