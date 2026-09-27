import math
from datetime import date, datetime, timezone

from .football_data import get_finished_matches
from .storage import (
    SALDO_INICIAL,
    connect,
    initialize_database,
)


FIXTURES_URL = "https://football-data.co.uk/fixtures.csv"


def initialize_paper_trading() -> None:
    initialize_database()

    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_bets (
                investment_id INTEGER PRIMARY KEY,
                match_key TEXT NOT NULL UNIQUE,
                division TEXT NOT NULL,
                match_date TEXT NOT NULL,
                home TEXT NOT NULL,
                away TEXT NOT NULL,
                selection TEXT NOT NULL
                    CHECK (selection IN ('H', 'D', 'A')),
                odds REAL NOT NULL CHECK (odds > 1),
                source_url TEXT NOT NULL,
                FOREIGN KEY (investment_id)
                    REFERENCES investments(id)
            )
            """
        )


def rule_is_valid(analysis: dict) -> bool:
    training = analysis["training"]
    validation = analysis["validation"]
    lower = validation["wilson_lower_bound"]

    return (
        training["bets"] >= 30
        and training["net_units"] > 0
        and validation["bets"] >= 30
        and validation["net_units"] > 0
        and lower is not None
        and lower >= 0.90
    )


def available_in_transaction(connection) -> float:
    """Calcula el saldo usando la conexión que tiene el bloqueo."""
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
        ) AS balance_change
        FROM investments
        """
    ).fetchone()

    return round(
        SALDO_INICIAL + row["balance_change"],
        2,
    )


def place_paper_bet(match: dict, analysis: dict) -> dict:
    """Abre una apuesta simulada si supera todos los filtros."""
    if not rule_is_valid(analysis):
        return {
            "placed": False,
            "reason": "La regla no pasó la validación histórica.",
        }

    if match.get("source") != FIXTURES_URL:
        return {
            "placed": False,
            "reason": "La fuente del partido no coincide.",
        }

    if match.get("division") != analysis.get("division"):
        return {
            "placed": False,
            "reason": "El análisis corresponde a otra liga.",
        }

    try:
        match_date = date.fromisoformat(match["date"])
        odds = match["odds"]
        selection = min(
            ("H", "D", "A"),
            key=lambda outcome: odds[outcome],
        )
        selected_odds = float(odds[selection])
        home = str(match["home"]).strip()
        away = str(match["away"]).strip()
        division = str(match["division"]).strip()
    except (KeyError, TypeError, ValueError):
        return {
            "placed": False,
            "reason": "Faltan datos del partido.",
        }

    if match_date <= datetime.now(timezone.utc).date():
        return {
            "placed": False,
            "reason": "El partido ya no tiene una fecha futura.",
        }

    if (
        not home
        or not away
        or not math.isfinite(selected_odds)
        or selected_odds <= 1
        or selected_odds > 1.30
    ):
        return {
            "placed": False,
            "reason": "El partido no cumple la regla de cuotas.",
        }

    match_key = (
        f"{division}|{match_date.isoformat()}|"
        f"{home.casefold()}|{away.casefold()}"
    )

    initialize_paper_trading()

    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            """
            SELECT investment_id
            FROM agent_bets
            WHERE match_key = ?
            """,
            (match_key,),
        ).fetchone()

        if existing:
            return {
                "placed": False,
                "reason": (
                    "Este partido ya tiene una apuesta registrada."
                ),
                "id": existing["investment_id"],
            }

        available = available_in_transaction(connection)
        stake = round(available * 0.01, 2)

        if stake < 0.01 or stake > available * 0.05:
            return {
                "placed": False,
                "reason": (
                    "El saldo no permite una apuesta de prueba."
                ),
            }

        name = (
            f"Fútbol: {home} vs {away} "
            f"({match_date.isoformat()}, {selection})"
        )

        cursor = connection.execute(
            """
            INSERT INTO investments (name, amount, origin)
            VALUES (?, ?, 'agent')
            """,
            (name, stake),
        )

        investment_id = int(cursor.lastrowid)

        connection.execute(
            """
            INSERT INTO agent_bets (
                investment_id, match_key, division,
                match_date, home, away, selection,
                odds, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                investment_id,
                match_key,
                division,
                match_date.isoformat(),
                home,
                away,
                selection,
                selected_odds,
                FIXTURES_URL,
            ),
        )

    return {
        "placed": True,
        "id": investment_id,
        "name": name,
        "stake": stake,
        "odds": selected_odds,
        "selection": selection,
    }


def settle_paper_bets() -> list[dict]:
    """Cierra una apuesta cuando la fuente publica el resultado."""
    initialize_paper_trading()

    with connect() as connection:
        pending = [
            dict(row)
            for row in connection.execute(
                """
                SELECT b.investment_id, b.division,
                       b.match_date, b.home, b.away,
                       b.selection, b.odds, i.amount
                FROM agent_bets AS b
                JOIN investments AS i
                  ON i.id = b.investment_id
                WHERE i.status = 'abierta'
                """
            ).fetchall()
        ]

    if not pending:
        return []

    finished_by_division = {}

    for division in {item["division"] for item in pending}:
        data = get_finished_matches(division)

        finished_by_division[division] = {
            (
                match["date"],
                match["home"].casefold(),
                match["away"].casefold(),
            ): match["result"]
            for match in data["matches"]
        }

    settled = []

    for item in pending:
        match_key = (
            item["match_date"],
            item["home"].casefold(),
            item["away"].casefold(),
        )

        result = finished_by_division[
            item["division"]
        ].get(match_key)

        if result not in {"H", "D", "A"}:
            continue

        returned = (
            round(item["amount"] * item["odds"], 2)
            if result == item["selection"]
            else 0.0
        )

        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")

            changed = connection.execute(
                """
                UPDATE investments
                SET returned_amount = ?,
                    status = 'cerrada',
                    closed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND status = 'abierta'
                  AND origin = 'agent'
                """,
                (returned, item["investment_id"]),
            ).rowcount

        if changed:
            settled.append({
                "id": item["investment_id"],
                "result": result,
                "returned_amount": returned,
            })

    return settled