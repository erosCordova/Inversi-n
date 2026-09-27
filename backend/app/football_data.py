import csv
import time
from datetime import datetime
from io import StringIO

import httpx


BASE_URL = "https://football-data.co.uk/mmz4281"
MAX_FILE_BYTES = 2_000_000
CACHE_SECONDS = 6 * 60 * 60

LEAGUES = {
    "E0": "Premier League",
    "E2": "League One",
    "E3": "League Two",
    "EC": "National League",
    "SP2": "Segunda División de España",
    "SC1": "Segunda División de Escocia",
}

SEASONS = {
    "2025/26": "2526",
    "2026/27": "2627",
}

_cache: dict[str, tuple[float, dict]] = {}


def parse_date(value: str) -> str:
    for pattern in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(
                value.strip(),
                pattern,
            ).date().isoformat()
        except ValueError:
            continue

    raise ValueError(f"Fecha no reconocida: {value}")


def get_finished_matches(division: str = "E0") -> dict:
    """Lee partidos terminados de una liga con cuotas históricas."""
    if division not in LEAGUES:
        raise ValueError(f"Liga no disponible: {division}")

    cached = _cache.get(division)

    if cached and time.monotonic() < cached[0]:
        return cached[1]

    matches = []

    for season, season_code in SEASONS.items():
        url = f"{BASE_URL}/{season_code}/{division}.csv"

        response = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=False,
            trust_env=False,
        )
        response.raise_for_status()

        if len(response.content) > MAX_FILE_BYTES:
            raise ValueError("El archivo de fútbol es demasiado grande.")

        reader = csv.DictReader(
            StringIO(
                response.content.decode(
                    "utf-8-sig",
                    errors="replace",
                )
            )
        )

        required = {
            "Date",
            "HomeTeam",
            "AwayTeam",
            "FTR",
            "B365H",
            "B365D",
            "B365A",
        }

        if not reader.fieldnames or not required.issubset(
            reader.fieldnames
        ):
            raise ValueError(
                f"Faltan columnas necesarias en {division} "
                f"{season}."
            )

        for row in reader:
            result = (row.get("FTR") or "").strip()

            if result not in {"H", "D", "A"}:
                continue

            try:
                odds = {
                    "H": float(row["B365H"]),
                    "D": float(row["B365D"]),
                    "A": float(row["B365A"]),
                }
                match_date = parse_date(row["Date"])

                if any(value <= 1 for value in odds.values()):
                    continue

            except (TypeError, ValueError):
                continue

            matches.append(
                {
                    "date": match_date,
                    "season": season,
                    "division": division,
                    "home": row["HomeTeam"],
                    "away": row["AwayTeam"],
                    "result": result,
                    "odds": odds,
                    "source": url,
                }
            )

    matches.sort(
        key=lambda match: (
            match["date"],
            match["home"],
            match["away"],
        )
    )

    data = {
        "league": LEAGUES[division],
        "division": division,
        "count": len(matches),
        "matches": matches,
    }

    _cache[division] = (
        time.monotonic() + CACHE_SECONDS,
        data,
    )

    return data