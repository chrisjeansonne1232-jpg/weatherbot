"""Polymarket price history (CLOB) and public trades (data-api). Read-only.

`prices-history` returns the *midpoint* of the best bid and ask at each timestamp (verified live:
0.0015 = mid(0.001, 0.002); 0.235 = mid(0.22, 0.25)). It is not a last trade and not a close, and
it says nothing about the ask a taker would actually pay. The backtest adds a measured spread.
"""

from __future__ import annotations

from . import http

CLOB = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
PRICE_FIDELITY_MIN = 5  # 5-minute points: hourly points were up to an hour stale at decision time


def price_history(token_id: str, start_ts: int, end_ts: int, fidelity_min: int = PRICE_FIDELITY_MIN) -> list[tuple[int, float]]:
    """[(unix_ts, midpoint)] for one outcome token, oldest first."""
    d = http.get(CLOB + "/prices-history", {"market": token_id, "startTs": int(start_ts), "endTs": int(end_ts),
                                            "fidelity": int(fidelity_min)})
    return [(int(x["t"]), float(x["p"])) for x in d.get("history", [])]


def trades(condition_id: str, limit: int = 500, offset: int = 0) -> list[dict]:
    """Public fills for one market (both outcomes), newest first."""
    return http.get(DATA_API + "/trades", {"market": condition_id, "limit": limit, "offset": offset,
                                            "takerOnly": "true"})
