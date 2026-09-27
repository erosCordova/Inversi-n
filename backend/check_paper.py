from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from app import paper_trading, storage


original_db_path = storage.DB_PATH
original_finished_matches = paper_trading.get_finished_matches

try:
    with TemporaryDirectory() as temporary:
        storage.DB_PATH = Path(temporary) / "prueba.db"

        match_date = (
            datetime.now(timezone.utc).date()
            + timedelta(days=1)
        ).isoformat()

        match = {
            "date": match_date,
            "division": "E0",
            "league": "Premier League",
            "home": "Equipo A",
            "away": "Equipo B",
            "odds": {
                "H": 1.25,
                "D": 5.0,
                "A": 9.0,
            },
            "source": paper_trading.FIXTURES_URL,
        }

        # Valores ficticios solo para probar el mecanismo.
        analysis = {
            "division": "E0",
            "training": {
                "bets": 100,
                "net_units": 5.0,
            },
            "validation": {
                "bets": 100,
                "net_units": 3.0,
                "wilson_lower_bound": 0.92,
            },
        }

        first = paper_trading.place_paper_bet(
            match,
            analysis,
        )
        repeated = paper_trading.place_paper_bet(
            match,
            analysis,
        )

        assert first["placed"] is True
        assert repeated["placed"] is False

        before = storage.get_portfolio()
        assert len(before["agent_open_investments"]) == 1

        paper_trading.get_finished_matches = lambda division: {
            "matches": [
                {
                    "date": match_date,
                    "home": "Equipo A",
                    "away": "Equipo B",
                    "result": "H",
                }
            ]
        }

        settled = paper_trading.settle_paper_bets()
        after = storage.get_portfolio()

        assert len(settled) == 1
        assert len(after["agent_open_investments"]) == 0
        assert len(after["agent_gains"]) == 1

        print("Apertura simulada:", first["placed"])
        print("Duplicado bloqueado:", not repeated["placed"])
        print("Apuesta cerrada:", len(settled) == 1)
        print("Saldo de prueba final:", after["available"])
        print("Base de datos real: sin cambios")

finally:
    storage.DB_PATH = original_db_path
    paper_trading.get_finished_matches = (
        original_finished_matches
    )
    