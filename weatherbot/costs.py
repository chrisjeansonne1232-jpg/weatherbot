"""Turns a historical MIDPOINT into the price a taker would really pay.

History only stores midpoints; real asks are higher. Spread by price level is measured from live
order books (tools/sample_books.py -> data/book_samples.jsonl, summarised by
tools/make_spread_table.py -> data/spread_table.json) and applied as:

    buy Yes  at  ask_yes = mid + spread(mid)/2      (rounded UP to the tick)
    buy No   at  ask_no  = 1 - bid_yes = 1 - mid + spread(mid)/2

The book is symmetric (Yes bid = 1 - No ask), so spread(mid) = spread(1 - mid).
Modes:  'typical'      -> median measured spread
        'conservative' -> 75th-percentile measured spread (the default used for every pass/fail call)
Order size is small (default 10 shares) so a fill is assumed to stay at the best ask; the measured
25th-percentile displayed depth at the best ask is 5-13 shares, which is why sizes are kept tiny.
"""

from __future__ import annotations

import json
import math

from . import http

TABLE_FILE = http.DATA_DIR / "spread_table.json"
# Fallback used only if no table has been built yet (values from the first live snapshot).
_DEFAULT = [  # (upper mid edge, median spread, p75 spread)
    (0.01, 0.003, 0.008), (0.03, 0.0155, 0.023), (0.08, 0.030, 0.040), (0.15, 0.030, 0.040),
    (0.30, 0.030, 0.040), (0.50001, 0.030, 0.035),
]


def _table():
    if TABLE_FILE.exists():
        return [tuple(x) for x in json.loads(TABLE_FILE.read_text())["buckets"]]
    return _DEFAULT


_T = None


def spread(mid: float, mode: str = "conservative") -> float:
    global _T
    if _T is None:
        _T = _table()
    m = min(mid, 1.0 - mid)
    for edge, med, p75 in _T:
        if m < edge:
            return p75 if mode == "conservative" else med
    return _T[-1][2] if mode == "conservative" else _T[-1][1]


def _ceil_tick(x: float, tick: float) -> float:
    return math.ceil(round(x / tick, 6)) * tick


def _floor_tick(x: float, tick: float) -> float:
    return math.floor(round(x / tick, 6)) * tick


def yes_bid_ask(mid: float, tick: float, mode: str = "conservative") -> tuple[float, float]:
    h = max(spread(mid, mode) / 2.0, tick / 2.0)
    ask = min(_ceil_tick(mid + h, tick), 1.0 - tick)
    bid = max(_floor_tick(mid - h, tick), tick)
    return bid, ask


def ask_prices(mid: float, tick: float, mode: str = "conservative") -> tuple[float, float]:
    """(price to buy Yes, price to buy No)."""
    bid, ask = yes_bid_ask(mid, tick, mode)
    return ask, 1.0 - bid
