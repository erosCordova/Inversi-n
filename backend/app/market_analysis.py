from .market_data import get_daily_prices
from .risk import wilson_lower_bound


# Supuesto de la simulación: 0,5 % al comprar y 0,5 % al vender.
# No representa necesariamente las tarifas de una plataforma real.
FEE_PER_SIDE = 0.005
HOLDING_DAYS = (1, 7)


def analyze_market(market: str) -> dict:
    data = get_daily_prices(market)
    prices = [item["close_usd"] for item in data["prices"]]
    scenarios = []

    for days in HOLDING_DAYS:
        results = []

        # Periodos separados: cada cierre se utiliza una sola vez
        # como final de una operación para este plazo.
        for start in range(0, len(prices) - days, days):
            buy_price = prices[start]
            sell_price = prices[start + days]

            net_return = (
                (sell_price / buy_price)
                * (1 - FEE_PER_SIDE)
                * (1 - FEE_PER_SIDE)
                - 1
            )
            results.append(net_return)

        trials = len(results)
        gains = sum(result > 0 for result in results)

        scenarios.append(
            {
                "holding_days": days,
                "trials": trials,
                "gains": gains,
                "historical_gain_rate": round(gains / trials, 4),
                "wilson_lower_bound": round(
                    wilson_lower_bound(gains, trials),
                    4,
                ),
                "average_net_return_pct": round(
                    sum(results) / trials * 100,
                    2,
                ),
            }
        )

    return {
        "market": market,
        "source": data["source"],
        "first_date": data["first_date"],
        "last_date": data["last_date"],
        "fee_per_side_assumed": FEE_PER_SIDE,
        "scenarios": scenarios,
    }