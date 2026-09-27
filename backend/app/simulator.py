from .football_data import get_finished_matches


STARTING_BALANCE = 1000.0
STAKE_FRACTION = 0.01
MAX_ODDS = 1.30


def simulate_football(
    division: str = "E0",
    season: str = "2025/26",
) -> dict:
    """Reproduce apuestas con partidos históricos terminados."""
    data = get_finished_matches(division)

    matches = sorted(
        (
            match
            for match in data["matches"]
            if match["season"] == season
        ),
        key=lambda match: (
            match["date"],
            match["home"],
            match["away"],
        ),
    )

    balance = STARTING_BALANCE
    operations = []

    for match in matches:
        odds = match["odds"]
        selection = min(
            ("H", "D", "A"),
            key=lambda result: odds[result],
        )
        selected_odds = odds[selection]

        if selected_odds > MAX_ODDS:
            continue

        stake = round(balance * STAKE_FRACTION, 2)

        if stake < 0.01:
            break

        won = match["result"] == selection
        returned = (
            round(stake * selected_odds, 2)
            if won
            else 0.0
        )

        balance = round(
            balance - stake + returned,
            2,
        )

        operations.append({
            "date": match["date"],
            "home": match["home"],
            "away": match["away"],
            "selection": selection,
            "odds": selected_odds,
            "stake": stake,
            "won": won,
            "returned": returned,
            "net": round(returned - stake, 2),
            "balance_after": balance,
            "source": match["source"],
        })

    wins = sum(
        operation["won"]
        for operation in operations
    )
    losses = len(operations) - wins

    return {
        "league": data["league"],
        "division": division,
        "season": season,
        "starting_balance": STARTING_BALANCE,
        "final_balance": balance,
        "net": round(
            balance - STARTING_BALANCE,
            2,
        ),
        "bets": len(operations),
        "wins": wins,
        "losses": losses,
        "operations": operations,
        "note": (
            "Simulación retrospectiva. No modificó "
            "el saldo de la cartera ni predice "
            "resultados futuros."
        ),
    }