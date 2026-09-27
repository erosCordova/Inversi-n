from datetime import datetime, timezone

import httpx

from .football_data import get_finished_matches
from .future_football import (
    finished_results,
    get_future_matches,
)
from .storage import connect


EXPERIMENT_BALANCE = 1000.0
BET_AMOUNT = 10.0
MAX_OPEN_BETS = 10
MIN_PROBABILITY = 0.50


def initialize_live_paper() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS live_paper_bets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_key TEXT NOT NULL UNIQUE,
                match_date TEXT NOT NULL,
                division TEXT NOT NULL,
                league TEXT NOT NULL,
                home TEXT NOT NULL,
                away TEXT NOT NULL,
                selection TEXT NOT NULL
                    CHECK (selection IN ('H', 'D', 'A')),
                odds REAL NOT NULL CHECK (odds > 1),
                amount REAL NOT NULL CHECK (amount > 0),
                status TEXT NOT NULL DEFAULT 'abierta'
                    CHECK (
                        status IN (
                            'abierta', 'ganada', 'perdida'
                        )
                    ),
                returned_amount REAL,
                source_url TEXT NOT NULL,
                created_at TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,
                settled_at TEXT
            )
            """
        )

        columns = {
            row["name"]
            for row in connection.execute(
                "PRAGMA table_info(live_paper_bets)"
            )
        }

        additions = {
            "estimated_probability": "REAL",
            "estimated_net_per_unit": "REAL",
            "training_matches": "INTEGER",
            "validation_matches": "INTEGER",
            "kickoff_utc": "TEXT",
            "home_odds": "REAL",
            "draw_odds": "REAL",
            "away_odds": "REAL",
            "final_result": "TEXT",
            "fixture_id": "INTEGER",
            "legacy_hidden": (
                "INTEGER NOT NULL DEFAULT 0"
            ),
        }

        for column, definition in additions.items():
            if column not in columns:
                connection.execute(
                    f"ALTER TABLE live_paper_bets "
                    f"ADD COLUMN {column} {definition}"
                )

        # Conserva las tres apuestas anteriores en SQLite,
        # pero las retira de la nueva lista activa.
        connection.execute(
            """
            UPDATE live_paper_bets
            SET legacy_hidden = 1
            WHERE division != 'API'
              AND legacy_hidden = 0
            """
        )


def experiment_status() -> dict:
    initialize_live_paper()

    with connect() as connection:
        all_bets = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM live_paper_bets
                ORDER BY id DESC
                """
            ).fetchall()
        ]

    open_bets = [
        bet for bet in all_bets
        if bet["status"] == "abierta"
    ]
    settled = [
        bet for bet in all_bets
        if bet["status"] != "abierta"
    ]

    invested = sum(
        bet["amount"] for bet in open_bets
    )
    net = sum(
        bet["returned_amount"] - bet["amount"]
        for bet in settled
    )

    upcoming = []
    upcoming_error = None

    try:
        upcoming = get_future_matches()["matches"]
    except (
        httpx.HTTPError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        upcoming_error = (
            "No se pudieron consultar los próximos "
            f"partidos: {type(error).__name__}."
        )

    return {
        "starting_balance": EXPERIMENT_BALANCE,
        "available": round(
            EXPERIMENT_BALANCE - invested + net,
            2,
        ),
        "invested": round(invested, 2),
        "net": round(net, 2),
        "bets": [
            bet for bet in all_bets
            if bet["legacy_hidden"] == 0
        ],
        "archived_bets": [
            bet for bet in all_bets
            if bet["legacy_hidden"] == 1
        ],
        "upcoming_matches": upcoming,
        "upcoming_error": upcoming_error,
        "note": (
            "Apuestas ficticias. Los porcentajes "
            "son probabilidades implícitas en cuotas, "
            "no predicciones validadas."
        ),
    }


def open_bet_count() -> int:
    initialize_live_paper()

    with connect() as connection:
        row = connection.execute(
            """
            SELECT COUNT(*) AS total
            FROM live_paper_bets
            WHERE status = 'abierta'
              AND legacy_hidden = 0
            """
        ).fetchone()
        return int(row["total"])


def _available(connection) -> float:
    row = connection.execute(
        """
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN status = 'abierta'
                        THEN -amount
                    ELSE returned_amount - amount
                END
            ),
            0
        ) AS change
        FROM live_paper_bets
        """
    ).fetchone()

    return EXPERIMENT_BALANCE + row["change"]


def choose_and_place_experiment(
    matches: list[dict] | None = None,
) -> dict:
    initialize_live_paper()

    if open_bet_count() >= MAX_OPEN_BETS:
        return {
            "placed": False,
            "reason": (
                "Ya hay diez apuestas ficticias "
                "activas."
            ),
        }

    if matches is None:
        matches = get_future_matches()["matches"]

    candidates = []

    for match in matches:
        for selection in ("H", "A"):
            probability = match[
                "probabilities"
            ][selection]

            if probability > MIN_PROBABILITY:
                candidates.append(
                    (
                        probability,
                        match,
                        selection,
                    )
                )

    candidates.sort(
        key=lambda row: (
            -row[0],
            row[1]["kickoff_utc"],
        )
    )

    for probability, match, selection in candidates:
        kickoff = datetime.fromisoformat(
            match["kickoff_utc"]
        )

        if kickoff <= datetime.now(timezone.utc):
            continue

        match_key = f"API|{match['fixture_id']}"

        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            existing = connection.execute(
                """
                SELECT id
                FROM live_paper_bets
                WHERE match_key = ?
                """,
                (match_key,),
            ).fetchone()

            if existing:
                continue

            count = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM live_paper_bets
                WHERE status = 'abierta'
                  AND legacy_hidden = 0
                """
            ).fetchone()["total"]

            if count >= MAX_OPEN_BETS:
                return {
                    "placed": False,
                    "reason": (
                        "Ya hay diez apuestas "
                        "ficticias activas."
                    ),
                }

            if _available(connection) < BET_AMOUNT:
                return {
                    "placed": False,
                    "reason": (
                        "No hay saldo ficticio "
                        "disponible."
                    ),
                }

            if kickoff <= datetime.now(timezone.utc):
                continue

            odds = match["odds"]
            cursor = connection.execute(
                """
                INSERT INTO live_paper_bets (
                    match_key, match_date,
                    division, league,
                    home, away, selection,
                    odds, amount, source_url,
                    estimated_probability,
                    kickoff_utc,
                    home_odds, draw_odds,
                    away_odds, fixture_id,
                    legacy_hidden
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, 0
                )
                """,
                (
                    match_key,
                    match["date"],
                    "API",
                    match["league"],
                    match["home"],
                    match["away"],
                    selection,
                    odds[selection],
                    BET_AMOUNT,
                    match["source"],
                    probability,
                    match["kickoff_utc"],
                    odds["H"],
                    odds["D"],
                    odds["A"],
                    match["fixture_id"],
                ),
            )

            return {
                "placed": True,
                "id": cursor.lastrowid,
                "match": (
                    f"{match['home']} vs "
                    f"{match['away']}"
                ),
                "selection": selection,
                "odds": odds[selection],
                "amount": BET_AMOUNT,
                "kickoff_utc": (
                    match["kickoff_utc"]
                ),
                "estimated_probability": probability,
                "validated": False,
            }

    return {
        "placed": False,
        "reason": (
            "No hay más partidos próximos "
            "con cuota y probabilidad implícita "
            "de victoria superior al 50 %."
        ),
    }


def settle_experiments() -> list[dict]:
    initialize_live_paper()

    with connect() as connection:
        pending = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM live_paper_bets
                WHERE status = 'abierta'
                """
            ).fetchall()
        ]

    api_dates = {
        bet["match_date"]
        for bet in pending
        if bet["division"] == "API"
    }

    api_results = (
        finished_results(api_dates)
        if api_dates else {}
    )

    old_results = {}
    old_divisions = {
        bet["division"]
        for bet in pending
        if bet["division"] != "API"
    }

    for division in old_divisions:
        history = get_finished_matches(division)
        old_results[division] = {
            (
                match["date"],
                match["home"].casefold(),
                match["away"].casefold(),
            ): match["result"]
            for match in history["matches"]
        }

    settled = []

    for bet in pending:
        if bet["division"] == "API":
            result = api_results.get(
                bet["fixture_id"]
            )
        else:
            result = old_results[
                bet["division"]
            ].get(
                (
                    bet["match_date"],
                    bet["home"].casefold(),
                    bet["away"].casefold(),
                )
            )

        if result not in {"H", "D", "A"}:
            continue

        won = result == bet["selection"]
        returned = (
            round(bet["amount"] * bet["odds"], 2)
            if won else 0.0
        )

        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            changed = connection.execute(
                """
                UPDATE live_paper_bets
                SET status = ?,
                    returned_amount = ?,
                    final_result = ?,
                    settled_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'abierta'
                """,
                (
                    "ganada" if won else "perdida",
                    returned,
                    result,
                    bet["id"],
                ),
            ).rowcount

        if changed:
            settled.append({
                "id": bet["id"],
                "match": (
                    f"{bet['home']} vs "
                    f"{bet['away']}"
                ),
                "won": won,
                "net": round(
                    returned - bet["amount"],
                    2,
                ),
            })

    return settled


def run_experiment_cycle() -> dict:
    settled = settle_experiments()
    placed_bets = []
    last_attempt = {
        "placed": False,
        "reason": (
            "No se encontraron partidos "
            "con cuotas disponibles."
        ),
    }

    matches = get_future_matches()["matches"]

    while open_bet_count() < MAX_OPEN_BETS:
        last_attempt = (
            choose_and_place_experiment(matches)
        )

        if not last_attempt["placed"]:
            break

        placed_bets.append(last_attempt)

    return {
        "settled": settled,
        "placed": (
            placed_bets[-1]
            if placed_bets
            else last_attempt
        ),
        "placed_bets": placed_bets,
        "portfolio": experiment_status(),
    }