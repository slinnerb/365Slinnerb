"""MLB Stats API wrapper. Uses the free public statsapi.mlb.com endpoints."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

import requests
from PIL import Image

BASE = "https://statsapi.mlb.com/api/v1"
HEADSHOT_URL = (
    "https://img.mlbstatic.com/mlb-photos/image/upload/"
    "d_people:generic:headshot:67:current.png/w_213,q_100/"
    "v1/people/{pid}/headshot/67/current"
)
TIMEOUT = 15


def current_season() -> int:
    return datetime.now().year


def _get(path: str, **params) -> dict[str, Any]:
    r = requests.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


@lru_cache(maxsize=1)
def get_teams() -> list[dict[str, Any]]:
    """Return all 30 active MLB teams, sorted by name."""
    data = _get("/teams", sportId=1, activeStatus="Y", season=current_season())
    teams = [
        {"id": t["id"], "name": t["name"], "abbreviation": t.get("abbreviation", "")}
        for t in data.get("teams", [])
    ]
    teams.sort(key=lambda t: t["name"])
    return teams


@lru_cache(maxsize=64)
def get_roster(team_id: int) -> list[dict[str, Any]]:
    """Return the active roster for a team."""
    data = _get(
        f"/teams/{team_id}/roster",
        rosterType="active",
        season=current_season(),
    )
    roster = []
    for r in data.get("roster", []):
        person = r.get("person", {})
        roster.append(
            {
                "id": person.get("id"),
                "fullName": person.get("fullName", ""),
                "position": r.get("position", {}).get("abbreviation", ""),
                "jerseyNumber": r.get("jerseyNumber", ""),
            }
        )
    roster.sort(key=lambda p: p["fullName"])
    return roster


_all_players_cache: list[dict[str, Any]] | None = None


def get_all_players() -> list[dict[str, Any]]:
    """Return every active player in MLB for the current season (for search).
    Manually cached — only stores non-empty results so a transient network failure
    on the first call doesn't get pinned for the rest of the session."""
    global _all_players_cache
    if _all_players_cache:
        return _all_players_cache
    data = _get("/sports/1/players", season=current_season())
    players = []
    for p in data.get("people", []):
        team = p.get("currentTeam") or {}
        players.append(
            {
                "id": p["id"],
                "fullName": p.get("fullName", ""),
                "teamId": team.get("id"),
                "teamName": team.get("name", ""),
                "position": (p.get("primaryPosition") or {}).get("abbreviation", ""),
            }
        )
    players.sort(key=lambda p: p["fullName"])
    if players:
        _all_players_cache = players
    return players


def player_index_size() -> int:
    """Return how many players are cached. 0 means the index hasn't successfully
    loaded yet — lets the UI distinguish 'still loading' from 'no matches'."""
    return len(_all_players_cache) if _all_players_cache else 0


@lru_cache(maxsize=512)
def get_player(player_id: int) -> dict[str, Any]:
    """Return full bio info for a single player."""
    data = _get(f"/people/{player_id}")
    people = data.get("people", [])
    return people[0] if people else {}


@lru_cache(maxsize=512)
def get_player_stats(player_id: int, group: str) -> dict[str, Any]:
    """Return current-season stats for hitting or pitching. Empty dict if none."""
    try:
        data = _get(
            f"/people/{player_id}/stats",
            stats="season",
            season=current_season(),
            group=group,
        )
    except requests.HTTPError:
        return {}
    for s in data.get("stats", []):
        for split in s.get("splits", []):
            stat = split.get("stat") or {}
            if stat:
                return stat
    return {}


@lru_cache(maxsize=256)
def get_player_history(player_id: int, group: str) -> dict[str, Any]:
    """Return {'career': {...}, 'seasons': [{'season': 'YYYY', 'stat': {...}}, ...]}
    for hitting or pitching, in a single API call. Empty pieces if unavailable."""
    try:
        data = _get(
            f"/people/{player_id}/stats",
            stats="career,yearByYear",
            group=group,
        )
    except requests.HTTPError:
        return {"career": {}, "seasons": []}
    career: dict[str, Any] = {}
    seasons: list[dict[str, Any]] = []
    for s in data.get("stats", []):
        type_name = (s.get("type") or {}).get("displayName")
        if type_name == "career":
            for split in s.get("splits", []):
                career = split.get("stat") or career
        elif type_name == "yearByYear":
            for split in s.get("splits", []):
                stat = split.get("stat") or {}
                season = split.get("season")
                if stat and season:
                    seasons.append({"season": season, "stat": stat})
    return {"career": career, "seasons": seasons}


def get_head_to_head(team_id: int, opponent_id: int, season: int | None = None) -> list[dict[str, Any]]:
    """Return this season's games between two teams (the season series), with scores."""
    if not team_id or not opponent_id:
        return []
    season = season or current_season()
    try:
        data = _get(
            "/schedule",
            sportId=1,
            teamId=team_id,
            opponentId=opponent_id,
            season=season,
            startDate=f"{season}-01-01",
            endDate=f"{season}-12-31",
        )
    except requests.HTTPError:
        return []
    games: list[dict[str, Any]] = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            home = (g.get("teams") or {}).get("home") or {}
            away = (g.get("teams") or {}).get("away") or {}
            games.append(
                {
                    "date": (g.get("gameDate") or "")[:10],
                    "away_name": (away.get("team") or {}).get("name", ""),
                    "away_score": away.get("score"),
                    "home_name": (home.get("team") or {}).get("name", ""),
                    "home_score": home.get("score"),
                    "status": (g.get("status") or {}).get("detailedState", ""),
                }
            )
    return games


def get_team_standing(team_id: int, season: int | None = None) -> dict[str, Any]:
    """Return a team's current W-L, division rank, games back, and streak."""
    if not team_id:
        return {}
    season = season or current_season()
    try:
        data = _get(
            "/standings",
            leagueId="103,104",
            season=season,
            standingsTypes="regularSeason",
        )
    except requests.HTTPError:
        return {}
    for rec in data.get("records", []):
        for tr in rec.get("teamRecords", []):
            if (tr.get("team") or {}).get("id") == team_id:
                return {
                    "wins": tr.get("wins"),
                    "losses": tr.get("losses"),
                    "pct": tr.get("winningPercentage"),
                    "divisionRank": tr.get("divisionRank"),
                    "leagueRank": tr.get("leagueRank"),
                    "gamesBack": tr.get("gamesBack"),
                    "streak": (tr.get("streak") or {}).get("streakCode"),
                    "division": DIVISION_NAMES.get((rec.get("division") or {}).get("id"), ""),
                }
    return {}


DIVISION_NAMES = {
    200: "AL West", 201: "AL East", 202: "AL Central",
    203: "NL West", 204: "NL East", 205: "NL Central",
}
DIVISION_ORDER = [201, 202, 200, 204, 205, 203]


def get_standings(season: int | None = None) -> list[dict[str, Any]]:
    """Return the six divisions in display order; each has its teams ranked 1st→last."""
    season = season or current_season()
    try:
        data = _get("/standings", leagueId="103,104", season=season, standingsTypes="regularSeason")
    except requests.HTTPError:
        return []
    by_div: dict[int, dict[str, Any]] = {}
    for rec in data.get("records", []):
        div_id = (rec.get("division") or {}).get("id")
        teams = []
        for tr in rec.get("teamRecords", []):
            teams.append(
                {
                    "id": (tr.get("team") or {}).get("id"),
                    "name": (tr.get("team") or {}).get("name", ""),
                    "wins": tr.get("wins"),
                    "losses": tr.get("losses"),
                    "pct": tr.get("winningPercentage"),
                    "gamesBack": tr.get("gamesBack"),
                    "divisionRank": tr.get("divisionRank"),
                    "streak": (tr.get("streak") or {}).get("streakCode"),
                }
            )

        def _rank(t):
            r = str(t.get("divisionRank", ""))
            return int(r) if r.isdigit() else 99

        teams.sort(key=_rank)
        if div_id is not None:
            by_div[div_id] = {"name": DIVISION_NAMES.get(div_id, "Division"), "teams": teams}
    return [by_div[d] for d in DIVISION_ORDER if d in by_div]


def get_leaders(category: str, group: str, limit: int = 15, season: int | None = None) -> list[dict[str, Any]]:
    """Return the top players for a single stat category."""
    season = season or current_season()
    try:
        data = _get(
            "/stats/leaders",
            leaderCategories=category, statGroup=group,
            season=season, sportId=1, limit=limit,
        )
    except requests.HTTPError:
        return []
    out: list[dict[str, Any]] = []
    for block in data.get("leagueLeaders", []):
        for ldr in block.get("leaders", []):
            out.append(
                {
                    "rank": ldr.get("rank"),
                    "id": (ldr.get("person") or {}).get("id"),
                    "name": (ldr.get("person") or {}).get("fullName", ""),
                    "team": (ldr.get("team") or {}).get("name", ""),
                    "value": ldr.get("value"),
                }
            )
        if out:
            break
    return out[:limit]


def get_team_games(team_id: int, season: int | None = None) -> dict[str, Any]:
    """Return {'last': game|None, 'next': game|None} for a team, around today."""
    if not team_id:
        return {"last": None, "next": None}
    today = datetime.now().date()
    start = today - timedelta(days=10)
    end = today + timedelta(days=14)
    try:
        data = _get(
            "/schedule",
            sportId=1, teamId=team_id,
            startDate=start.isoformat(), endDate=end.isoformat(),
            hydrate="probablePitcher",
        )
    except requests.HTTPError:
        return {"last": None, "next": None}

    games = [g for d in data.get("dates", []) for g in d.get("games", [])]

    def simplify(g):
        home = (g.get("teams") or {}).get("home") or {}
        away = (g.get("teams") or {}).get("away") or {}
        st = g.get("status") or {}
        return {
            "gamePk": g.get("gamePk"),
            "date": (g.get("gameDate") or "")[:10],
            "gameDate": g.get("gameDate"),
            "status": st.get("detailedState", ""),
            "home_name": (home.get("team") or {}).get("name", ""),
            "home_score": home.get("score"),
            "away_name": (away.get("team") or {}).get("name", ""),
            "away_score": away.get("score"),
        }

    finals = [g for g in games if (g.get("status") or {}).get("abstractGameState") == "Final"]
    upcoming = [g for g in games if (g.get("status") or {}).get("abstractGameState") in ("Preview", "Live")]
    last = simplify(sorted(finals, key=lambda g: g.get("gameDate", ""))[-1]) if finals else None
    nxt = simplify(sorted(upcoming, key=lambda g: g.get("gameDate", ""))[0]) if upcoming else None
    return {"last": last, "next": nxt}


@lru_cache(maxsize=512)
def get_pitch_arsenal(player_id: int) -> dict[str, Any]:
    """Return {'season': YYYY|None, 'pitches': [...]} — average velocity, usage %, and count
    per pitch type for a pitcher. Falls back to previous season if the current one is empty
    (useful early in a season or for pitchers who haven't thrown yet). Empty for non-pitchers."""
    for season in (current_season(), current_season() - 1):
        try:
            data = _get(
                f"/people/{player_id}/stats",
                stats="pitchArsenal",
                group="pitching",
                season=season,
            )
        except requests.HTTPError:
            continue
        pitches = []
        for s in data.get("stats", []):
            for split in s.get("splits", []):
                stat = split.get("stat") or {}
                ptype = stat.get("type") or {}
                pitches.append(
                    {
                        "code": ptype.get("code"),
                        "description": ptype.get("description") or ptype.get("code") or "—",
                        "averageSpeed": stat.get("averageSpeed"),
                        "percentage": stat.get("percentage"),
                        "count": stat.get("count"),
                        "totalPitches": stat.get("totalPitches"),
                    }
                )
        if pitches:
            pitches.sort(key=lambda p: (p.get("percentage") or 0), reverse=True)
            return {"season": season, "pitches": pitches}
    return {"season": None, "pitches": []}


@lru_cache(maxsize=512)
def get_headshot(player_id: int) -> Image.Image | None:
    """Fetch player headshot as a PIL Image. Returns None on failure."""
    try:
        r = requests.get(HEADSHOT_URL.format(pid=player_id), timeout=TIMEOUT)
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGBA")
    except Exception:
        return None


def search_players(query: str, limit: int = 100) -> list[dict[str, Any]]:
    """Case-insensitive substring match across all current players. Returns []
    quietly if the player index hasn't loaded yet."""
    q = query.strip().lower()
    if not q:
        return []
    try:
        all_players = get_all_players()
    except Exception:
        return []
    matches = [p for p in all_players if q in p["fullName"].lower()]
    return matches[:limit]


def _format_record(rec: dict[str, Any] | None) -> str:
    if not rec:
        return ""
    return f"{rec.get('wins', 0)}-{rec.get('losses', 0)}"


def get_schedule(date_iso: str) -> list[dict[str, Any]]:
    """Return the MLB schedule for a given date (YYYY-MM-DD)."""
    data = _get(
        "/schedule",
        sportId=1,
        date=date_iso,
        hydrate="probablePitcher,linescore",
    )
    games: list[dict[str, Any]] = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            home = (g.get("teams") or {}).get("home") or {}
            away = (g.get("teams") or {}).get("away") or {}
            home_pitcher = home.get("probablePitcher") or {}
            away_pitcher = away.get("probablePitcher") or {}
            status = g.get("status") or {}
            games.append(
                {
                    "gamePk": g.get("gamePk"),
                    "gameDate": g.get("gameDate"),
                    "status": status.get("detailedState", "Scheduled"),
                    "abstractState": status.get("abstractGameState", ""),
                    "venue": (g.get("venue") or {}).get("name", ""),
                    "home": {
                        "id": (home.get("team") or {}).get("id"),
                        "name": (home.get("team") or {}).get("name", ""),
                        "score": home.get("score"),
                        "record": _format_record(home.get("leagueRecord")),
                        "pitcherId": home_pitcher.get("id"),
                        "pitcherName": home_pitcher.get("fullName") or "TBD",
                    },
                    "away": {
                        "id": (away.get("team") or {}).get("id"),
                        "name": (away.get("team") or {}).get("name", ""),
                        "score": away.get("score"),
                        "record": _format_record(away.get("leagueRecord")),
                        "pitcherId": away_pitcher.get("id"),
                        "pitcherName": away_pitcher.get("fullName") or "TBD",
                    },
                }
            )
    return games


@lru_cache(maxsize=512)
def get_player_recent_stats(
    player_id: int, group: str, days: int = 7
) -> dict[str, Any]:
    """Return totals over the last N calendar days for hitting or pitching.
    Empty dict if no games played in range."""
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)
    try:
        data = _get(
            f"/people/{player_id}/stats",
            stats="byDateRange",
            group=group,
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            season=current_season(),
        )
    except requests.HTTPError:
        return {}
    for s in data.get("stats", []):
        for split in s.get("splits", []):
            stat = split.get("stat") or {}
            if stat:
                return stat
    return {}


def get_game_detail(game_pk: int) -> dict[str, Any]:
    """Fetch the live feed for a game and reduce it to what the UI needs.
    Always hits the network — never cached, since live games change every pitch."""
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    r = requests.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()

    gd = data.get("gameData", {}) or {}
    ld = data.get("liveData", {}) or {}
    status = gd.get("status", {}) or {}
    teams_meta = gd.get("teams", {}) or {}
    venue = (gd.get("venue") or {}).get("name", "")
    datetime_iso = (gd.get("datetime") or {}).get("dateTime") or (gd.get("datetime") or {}).get("originalDate")

    linescore = ld.get("linescore", {}) or {}
    boxscore = ld.get("boxscore", {}) or {}
    plays = ld.get("plays", {}) or {}
    current_play = plays.get("currentPlay") or {}

    probable_pitchers = gd.get("probablePitchers", {}) or {}

    def _team_summary(side: str) -> dict[str, Any]:
        meta = teams_meta.get(side, {}) or {}
        ls_team = (linescore.get("teams", {}) or {}).get(side, {}) or {}
        bs_team = (boxscore.get("teams", {}) or {}).get(side, {}) or {}
        pp = probable_pitchers.get(side) or {}
        return {
            "id": meta.get("id"),
            "name": meta.get("name", ""),
            "abbreviation": meta.get("abbreviation", ""),
            "runs": ls_team.get("runs"),
            "hits": ls_team.get("hits"),
            "errors": ls_team.get("errors"),
            "leftOnBase": ls_team.get("leftOnBase"),
            "probablePitcherId": pp.get("id"),
            "probablePitcherName": pp.get("fullName", ""),
            "players": _extract_players(bs_team),
            "battingOrder": bs_team.get("battingOrder", []),
            "pitchers": bs_team.get("pitchers", []),
        }

    innings_rows: list[dict[str, Any]] = []
    for inning in linescore.get("innings", []) or []:
        innings_rows.append(
            {
                "num": inning.get("num"),
                "ordinal": inning.get("ordinalNum", str(inning.get("num", ""))),
                "away_runs": (inning.get("away") or {}).get("runs"),
                "home_runs": (inning.get("home") or {}).get("runs"),
            }
        )

    offense = linescore.get("offense", {}) or {}
    on_base = {
        "first": bool(offense.get("first")),
        "second": bool(offense.get("second")),
        "third": bool(offense.get("third")),
    }
    batter = (offense.get("batter") or {})
    on_deck = (offense.get("onDeck") or {})

    defense = linescore.get("defense", {}) or {}
    pitcher = (defense.get("pitcher") or {})

    cp_result = current_play.get("result", {}) or {}
    cp_about = current_play.get("about", {}) or {}

    return {
        "gamePk": game_pk,
        "status": {
            "detailed": status.get("detailedState", "Scheduled"),
            "abstract": status.get("abstractGameState", ""),
            "isFinal": status.get("abstractGameState") == "Final",
            "isLive": status.get("abstractGameState") == "Live",
        },
        "venue": venue,
        "datetime": datetime_iso,
        "scheduledInnings": linescore.get("scheduledInnings", 9),
        "currentInning": linescore.get("currentInning"),
        "currentInningOrdinal": linescore.get("currentInningOrdinal"),
        "inningHalf": linescore.get("inningHalf"),
        "inningState": linescore.get("inningState"),
        "isTopInning": linescore.get("isTopInning"),
        "outs": linescore.get("outs"),
        "balls": linescore.get("balls"),
        "strikes": linescore.get("strikes"),
        "onBase": on_base,
        "currentBatter": {"id": batter.get("id"), "name": batter.get("fullName", "")},
        "onDeck": {"id": on_deck.get("id"), "name": on_deck.get("fullName", "")},
        "currentPitcher": {"id": pitcher.get("id"), "name": pitcher.get("fullName", "")},
        "currentPlay": {
            "description": cp_result.get("description", ""),
            "event": cp_result.get("event", ""),
            "halfInning": cp_about.get("halfInning"),
            "inning": cp_about.get("inning"),
        },
        "innings": innings_rows,
        "away": _team_summary("away"),
        "home": _team_summary("home"),
    }


def _extract_players(team_box: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the {ID..: {...}} player map of a boxscore team into a list."""
    out: list[dict[str, Any]] = []
    for _pid, pdata in (team_box.get("players") or {}).items():
        person = pdata.get("person") or {}
        position = pdata.get("position") or {}
        stats = pdata.get("stats") or {}
        batting = stats.get("batting") or {}
        pitching = stats.get("pitching") or {}
        out.append(
            {
                "id": person.get("id"),
                "name": person.get("fullName", ""),
                "position": position.get("abbreviation", ""),
                "batting": {
                    "ab": batting.get("atBats"),
                    "r": batting.get("runs"),
                    "h": batting.get("hits"),
                    "rbi": batting.get("rbi"),
                    "bb": batting.get("baseOnBalls"),
                    "k": batting.get("strikeOuts"),
                    "hr": batting.get("homeRuns"),
                    "avg": batting.get("avg"),
                },
                "pitching": {
                    "ip": pitching.get("inningsPitched"),
                    "h": pitching.get("hits"),
                    "r": pitching.get("runs"),
                    "er": pitching.get("earnedRuns"),
                    "bb": pitching.get("baseOnBalls"),
                    "k": pitching.get("strikeOuts"),
                    "era": pitching.get("era"),
                    "decision": pitching.get("note", ""),
                },
            }
        )
    return out


def gameday_url(game_pk: int) -> str:
    return f"https://www.mlb.com/gameday/{game_pk}"


def mlbtv_url(game_pk: int) -> str:
    return f"https://www.mlb.com/tv/g{game_pk}"


def ip_to_float(ip_value: Any) -> float | None:
    """Convert MLB innings notation ('5.1' = 5 1/3, '5.2' = 5 2/3) to true float."""
    if ip_value is None or ip_value == "":
        return None
    try:
        s = str(ip_value)
        if "." in s:
            whole, frac = s.split(".", 1)
            outs = int(frac)
            if outs not in (0, 1, 2):
                return float(s)
            return int(whole) + outs / 3.0
        return float(s)
    except (ValueError, AttributeError):
        return None
