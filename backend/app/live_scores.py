import os
import threading
import time

import httpx
from dotenv import load_dotenv


load_dotenv()

API_URL = "https://v3.football.api-sports.io/fixtures"
CACHE_SECONDS = 60 * 60
RETRY_SECONDS = 30 * 60

_cache_lock = threading.Lock()
_next_request_at = 0.0
_cached_matches: list[dict] = []
_last_message = ""
_is_stale = False


def _temporary_failure(detail: str) -> dict:
    global _next_request_at
    global _last_message
    global _is_stale

    _next_request_at = time.monotonic() + RETRY_SECONDS
    _last_message = (
        "Marcadores temporalmente no disponibles "
        f"({detail}). Se intentará de nuevo "
        "en 30 minutos."
    )
    _is_stale = True

    return {
        "configured": True,
        "matches": _cached_matches,
        "message": _last_message,
        "stale": True,
    }


def get_live_matches() -> dict:
    global _next_request_at
    global _cached_matches
    global _last_message
    global _is_stale

    api_key = os.getenv("API_SPORTS_KEY", "").strip()

    if not api_key:
        return {
            "configured": False,
            "matches": [],
            "message": (
                "Falta API_SPORTS_KEY en backend/.env."
            ),
            "stale": False,
        }

    with _cache_lock:
        if time.monotonic() < _next_request_at:
            return {
                "configured": True,
                "matches": _cached_matches,
                "message": _last_message,
                "stale": _is_stale,
            }

        try:
            response = httpx.get(
                API_URL,
                params={"live": "all"},
                headers={
                    "x-apisports-key": api_key,
                },
                timeout=12,
                trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()

            if payload.get("errors"):
                return _temporary_failure(
                    "consulta rechazada por la API"
                )

            matches = []

            for item in payload.get("response", []):
                fixture = item.get("fixture") or {}
                league = item.get("league") or {}
                teams = item.get("teams") or {}
                goals = item.get("goals") or {}
                state = fixture.get("status") or {}

                home = teams.get("home") or {}
                away = teams.get("away") or {}

                matches.append({
                    "id": fixture.get("id"),
                    "kickoff_utc": fixture.get("date"),
                    "league": league.get("name"),
                    "home": home.get("name"),
                    "away": away.get("name"),
                    "home_goals": goals.get("home"),
                    "away_goals": goals.get("away"),
                    "minute": state.get("elapsed"),
                    "status": state.get("short"),
                    "source": "API-Sports",
                })

            _cached_matches = matches
            _next_request_at = (
                time.monotonic() + CACHE_SECONDS
            )
            _last_message = (
                "Marcadores consultados. "
                "Se actualizan hasta cada hora."
            )
            _is_stale = False

            return {
                "configured": True,
                "matches": matches,
                "message": _last_message,
                "stale": False,
            }

        except httpx.HTTPStatusError as error:
            response = getattr(error, "response", None)
            code = getattr(
                response,
                "status_code",
                "desconocido",
            )
            return _temporary_failure(f"HTTP {code}")

        except (httpx.HTTPError, ValueError) as error:
            return _temporary_failure(
                type(error).__name__
            )