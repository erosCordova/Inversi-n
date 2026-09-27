from datetime import datetime, timezone

import httpx


KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"

MARKETS = {
    "BTC/USD": "XBTUSD",
    "ETH/USD": "ETHUSD",
    "SOL/USD": "SOLUSD",
}


def get_daily_prices(market: str) -> dict:
    """Obtiene precios diarios cerrados para una simulación."""
    if market not in MARKETS:
        raise ValueError(f"Mercado no disponible: {market}")

    response = httpx.get(
        KRAKEN_OHLC_URL,
        params={
            "pair": MARKETS[market],
            "interval": 1440,
        },
        timeout=15.0,
        trust_env=False,
    )
    response.raise_for_status()

    payload = response.json()

    if payload.get("error"):
        raise ValueError(
            "Error de Kraken: "
            + ", ".join(str(item) for item in payload["error"])
        )

    result = payload.get("result", {})
    pair_keys = [key for key in result if key != "last"]

    if len(pair_keys) != 1:
        raise ValueError("Respuesta de precios inesperada.")

    # La última vela todavía está en curso y puede cambiar.
    closed_candles = result[pair_keys[0]][:-1]

    if len(closed_candles) < 60:
        raise ValueError("No hay suficientes precios diarios.")

    prices = []

    for candle in closed_candles:
        close = float(candle[4])

        if close <= 0:
            raise ValueError("Se recibió un precio no válido.")

        prices.append(
            {
                "date": datetime.fromtimestamp(
                    int(candle[0]),
                    tz=timezone.utc,
                ).date().isoformat(),
                "close_usd": close,
            }
        )

    return {
        "market": market,
        "currency": "USD",
        "source": KRAKEN_OHLC_URL,
        "first_date": prices[0]["date"],
        "last_date": prices[-1]["date"],
        "count": len(prices),
        "prices": prices,
    }