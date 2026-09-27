import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv


load_dotenv()

BASE_URL = "https://v3.football.api-sports.io"
FIXTURE_CACHE_SECONDS = 2 * 60 * 60
ODDS_CACHE_SECONDS = 6 * 60 * 60
ODDS_SCAN_SECONDS = 15 * 60
MAX_ODDS_PER_SCAN = 5
MAX_ODDS_REQUESTS_PER_UTC_DAY = 35
MAX_HOURS_AHEAD = 12

_lock = threading.RLock()
_fixture_cache: dict[str, tuple[float, list[dict]]] = {}
_odds_cache: dict[int, tuple[float, dict | None]] = {}
_odds_day = ""
_odds_requests_today = 0
_next_odds_scan = 0.0
_blocked_until = 0.0


def _request(path: str, params: dict) -> dict:
    key = os.getenv("API_SPORTS_KEY", "").strip()
    if not key:
        raise ValueError(
            "Falta API_SPORTS_KEY en backend/.env."
        )

    response = httpx.get(
        f"{BASE_URL}/{path}",
        params=params,
        headers={"x-apisports-key": key},
        timeout=18,
        trust_env=False,
    )
    response.raise_for_status()
    payload = response.json()

    if payload.get("errors"):
        raise ValueError(
            f"API-Sports rechazó {path}: "
            f"{payload['errors']}"
        )

    return payload


def _fixtures_on(date_string: str) -> list[dict]:
    with _lock:
        cached = _fixture_cache.get(date_string)

        if cached and time.monotonic() < cached[0]:
            return cached[1]

        try:
            payload = _request(
                "fixtures",
                {
                    "date": date_string,
                    "timezone": "UTC",
                },
            )
            fixtures = payload.get("response") or []
            _fixture_cache[date_string] = (
                time.monotonic() + FIXTURE_CACHE_SECONDS,
                fixtures,
            )
            return fixtures
        except (httpx.HTTPError, ValueError):
            if cached:
                return cached[1]
            raise


def _valid_odds(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number) or number <= 1:
        return None

    return number


def _match_winner_odds(payload: dict) -> dict | None:
    best = None
    best_margin = float("inf")

    for record in payload.get("response") or []:
        for bookmaker in record.get("bookmakers") or []:
            for bet in bookmaker.get("bets") or []:
                if (
                    bet.get("id") != 1
                    and str(
                        bet.get("name", "")
                    ).lower() != "match winner"
                ):
                    continue

                values = {}

                for entry in bet.get("values") or []:
                    label = str(
                        entry.get("value", "")
                    ).strip().lower()

                    choice = {
                        "home": "H",
                        "1": "H",
                        "draw": "D",
                        "x": "D",
                        "away": "A",
                        "2": "A",
                    }.get(label)

                    if choice:
                        values[choice] = _valid_odds(
                            entry.get("odd")
                        )

                if (
                    set(values) != {"H", "D", "A"}
                    or any(
                        value is None
                        for value in values.values()
                    )
                ):
                    continue

                odds = {
                    choice: float(value)
                    for choice, value in values.items()
                    if value is not None
                }

                margin = sum(
                    1 / value
                    for value in odds.values()
                )

                if margin < best_margin:
                    best_margin = margin
                    best = {
                        "odds": odds,
                        "bookmaker": (
                            bookmaker.get("name")
                        ),
                    }

    return best


def _odds_for_fixture(
    fixture_id: int,
    allow_request: bool,
) -> tuple[dict | None, bool]:
    global _odds_day
    global _odds_requests_today
    global _blocked_until

    cached = _odds_cache.get(fixture_id)

    if cached and time.monotonic() < cached[0]:
        return cached[1], False

    today = datetime.now(
        timezone.utc
    ).date().isoformat()

    if today != _odds_day:
        _odds_day = today
        _odds_requests_today = 0

    if (
        not allow_request
        or time.monotonic() < _blocked_until
        or _odds_requests_today
            >= MAX_ODDS_REQUESTS_PER_UTC_DAY
    ):
        return None, False

    _odds_requests_today += 1

    try:
        payload = _request(
            "odds",
            {
                "fixture": fixture_id,
                "bet": 1,
            },
        )
        result = _match_winner_odds(payload)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 429:
            _blocked_until = (
                time.monotonic() + 90
            )
            return None, True
        result = None
    except (httpx.HTTPError, ValueError):
        result = None

    _odds_cache[fixture_id] = (
        time.monotonic() + ODDS_CACHE_SECONDS,
        result,
    )

    return result, True


def _probabilities(
    odds: dict[str, float],
) -> dict[str, float]:
    inverse = {
        choice: 1 / value
        for choice, value in odds.items()
    }
    total = sum(inverse.values())

    return {
        choice: round(value / total, 4)
        for choice, value in inverse.items()
    }


def get_future_matches() -> dict:
    global _next_odds_scan

    with _lock:
        now = datetime.now(timezone.utc)
        end = now + timedelta(
            hours=MAX_HOURS_AHEAD
        )

        dates = {
            now.date().isoformat(),
            end.date().isoformat(),
        }
        scheduled = []

        for date_string in sorted(dates):
            for item in _fixtures_on(date_string):
                fixture = item.get("fixture") or {}
                status = (
                    fixture.get("status") or {}
                )

                if status.get("short") != "NS":
                    continue

                try:
                    kickoff = (
                        datetime.fromisoformat(
                            fixture["date"].replace(
                                "Z", "+00:00"
                            )
                        ).astimezone(timezone.utc)
                    )
                    fixture_id = int(
                        fixture["id"]
                    )
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    continue

                if not now < kickoff <= end:
                    continue

                teams = item.get("teams") or {}
                home = (
                    teams.get("home") or {}
                ).get("name")
                away = (
                    teams.get("away") or {}
                ).get("name")

                if not home or not away:
                    continue

                scheduled.append(
                    (
                        kickoff,
                        fixture_id,
                        item,
                    )
                )

        scheduled.sort(
            key=lambda row: row[0]
        )

        scan_allowed = (
            time.monotonic()
            >= _next_odds_scan
        )

        if scan_allowed:
            _next_odds_scan = (
                time.monotonic()
                + ODDS_SCAN_SECONDS
            )

        requests_this_scan = 0
        matches = []

        for kickoff, fixture_id, item in scheduled[:35]:
            allow_request = (
                scan_allowed
                and requests_this_scan
                    < MAX_ODDS_PER_SCAN
            )

            quoted, requested = (
                _odds_for_fixture(
                    fixture_id,
                    allow_request,
                )
            )

            if requested:
                requests_this_scan += 1

            if quoted is None:
                continue

            teams = item["teams"]
            league = item.get("league") or {}
            odds = quoted["odds"]

            matches.append({
                "fixture_id": fixture_id,
                "date": (
                    kickoff.date().isoformat()
                ),
                "kickoff_utc": (
                    kickoff.isoformat()
                ),
                "division": "API",
                "league": (
                    league.get("name")
                    or "Fútbol"
                ),
                "home": (
                    teams["home"]["name"]
                ),
                "away": (
                    teams["away"]["name"]
                ),
                "odds": odds,
                "probabilities": (
                    _probabilities(odds)
                ),
                "bookmaker": (
                    quoted["bookmaker"]
                ),
                "source": (
                    f"{BASE_URL}/odds"
                    f"?fixture={fixture_id}"
                ),
            })

        return {
            "count": len(matches),
            "matches": matches,
            "checked_fixtures": min(
                len(scheduled), 35
            ),
            "odds_requests_today": (
                _odds_requests_today
            ),
        }


def finished_results(
    date_strings: set[str],
) -> dict[int, str]:
    """Resultados a los 90 minutos."""
    results = {}

    for date_string in date_strings:
        for item in _fixtures_on(date_string):
            fixture = item.get("fixture") or {}
            status = (
                fixture.get("status") or {}
            )

            if status.get("short") not in {
                "FT", "AET", "PEN"
            }:
                continue

            fulltime = (
                (item.get("score") or {})
                .get("fulltime") or {}
            )
            home = fulltime.get("home")
            away = fulltime.get("away")

            if home is None or away is None:
                continue

            result = (
                "H" if home > away
                else "A" if away > home
                else "D"
            )

            try:
                results[
                    int(fixture["id"])
                ] = result
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

    return results