import math

from .football_data import get_finished_matches
from .risk import wilson_lower_bound


MAX_FAVORITE_ODDS = 1.30
STAKE_PER_MATCH = 1.0
PRIOR_WEIGHT = 30


def evaluate_season(
    matches: list[dict],
    season: str,
) -> dict:
    """Conserva el análisis anterior para el resto del agente."""
    results = []

    for match in matches:
        if match["season"] != season:
            continue

        outcome, odds = min(
            match["odds"].items(),
            key=lambda item: item[1],
        )

        if odds > MAX_FAVORITE_ODDS:
            continue

        won = match["result"] == outcome
        profit = (
            STAKE_PER_MATCH * (odds - 1)
            if won
            else -STAKE_PER_MATCH
        )

        results.append({
            "won": won,
            "profit": profit,
        })

    trials = len(results)
    wins = sum(
        item["won"]
        for item in results
    )
    net = sum(
        item["profit"]
        for item in results
    )

    return {
        "season": season,
        "bets": trials,
        "wins": wins,
        "win_rate": (
            round(wins / trials, 4)
            if trials
            else None
        ),
        "wilson_lower_bound": (
            round(
                wilson_lower_bound(
                    wins,
                    trials,
                ),
                4,
            )
            if trials
            else None
        ),
        "net_units": round(net, 2),
        "return_per_bet": (
            round(net / trials, 4)
            if trials
            else None
        ),
    }


def analyze_favorite_strategy(
    division: str = "E0",
) -> dict:
    data = get_finished_matches(division)
    matches = data["matches"]

    return {
        "division": division,
        "league": data["league"],
        "source": (
            "https://football-data.co.uk/mmz4281/"
            f"2526/{division}.csv"
        ),
        "rule": (
            "Apostar 1 unidad al resultado "
            "con menor cuota solo si su "
            "cuota es <= 1.30"
        ),
        "training": evaluate_season(
            matches,
            "2025/26",
        ),
        "validation": evaluate_season(
            matches,
            "2026/27",
        ),
    }


def similar_results(
    historical: list[dict],
    season: str,
    selection: str,
    current_odds: float,
) -> dict:
    """Busca el mismo resultado en cuotas parecidas."""
    tolerance = max(
        0.15,
        current_odds * 0.10,
    )

    comparable = [
        match
        for match in historical
        if (
            match["season"] == season
            and math.isfinite(
                match["odds"][selection]
            )
            and abs(
                match["odds"][selection]
                - current_odds
            ) <= tolerance
        )
    ]

    wins = sum(
        match["result"] == selection
        for match in comparable
    )
    trials = len(comparable)

    net_units = sum(
        (
            match["odds"][selection] - 1
            if match["result"] == selection
            else -1
        )
        for match in comparable
    )

    return {
        "trials": trials,
        "wins": wins,
        "win_rate": (
            round(wins / trials, 4)
            if trials
            else None
        ),
        "net_units": round(
            net_units,
            2,
        ),
        "lower_bound": (
            round(
                wilson_lower_bound(
                    wins,
                    trials,
                ),
                4,
            )
            if trials
            else None
        ),
    }


def assess_fixture(
    fixture: dict,
    historical: list[dict] | None = None,
) -> list[dict]:
    """Evalúa local, empate y visitante por separado."""
    if historical is None:
        historical = get_finished_matches(
            fixture["division"]
        )["matches"]

    odds = fixture["odds"]

    if any(
        not math.isfinite(odds[outcome])
        or odds[outcome] <= 1
        for outcome in ("H", "D", "A")
    ):
        raise ValueError(
            "Las cuotas del partido no son válidas."
        )

    inverse_total = sum(
        1 / odds[outcome]
        for outcome in ("H", "D", "A")
    )

    assessments = []

    for selection in ("H", "D", "A"):
        current_odds = odds[selection]

        # Se retira aproximadamente el margen
        # proporcional de las tres cuotas.
        market_probability = (
            (1 / current_odds)
            / inverse_total
        )

        training = similar_results(
            historical,
            "2025/26",
            selection,
            current_odds,
        )

        validation = similar_results(
            historical,
            "2026/27",
            selection,
            current_odds,
        )

        # La evidencia histórica modifica gradualmente
        # la probabilidad implícita del mercado.
        estimated_probability = (
            training["wins"]
            + PRIOR_WEIGHT
            * market_probability
        ) / (
            training["trials"]
            + PRIOR_WEIGHT
        )

        expected_net_per_unit = (
            estimated_probability
            * current_odds
            - 1
        )

        lower = validation["lower_bound"]

        conservative_net_per_unit = (
            lower * current_odds - 1
            if (
                validation["trials"] >= 30
                and lower is not None
            )
            else None
        )

        validated = (
            training["trials"] >= 30
            and training["net_units"] > 0
            and validation["trials"] >= 30
            and validation["net_units"] > 0
            and conservative_net_per_unit
                is not None
            and conservative_net_per_unit > 0.05
        )

        assessments.append({
            "selection": selection,
            "odds": current_odds,
            "market_probability": round(
                market_probability,
                4,
            ),
            "estimated_probability": round(
                estimated_probability,
                4,
            ),
            "expected_net_per_unit": round(
                expected_net_per_unit,
                4,
            ),
            "conservative_net_per_unit": (
                round(
                    conservative_net_per_unit,
                    4,
                )
                if conservative_net_per_unit
                    is not None
                else None
            ),
            "training": training,
            "validation": validation,
            "validated": validated,
            "note": (
                "Estimación experimental; "
                "no predice con certeza "
                "el resultado del partido."
            ),
        })

    return sorted(
        assessments,
        key=lambda item: (
            item["expected_net_per_unit"],
            item["training"]["trials"],
        ),
        reverse=True,
    )