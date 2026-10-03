"""Polymarket taker fee for the weather markets (docs.polymarket.com/trading/fees).

    fee = shares * rate * p * (1 - p)        rate = 0.05, taker only, rounded to 5 decimals

Makers pay nothing (and earn a 25% rebate); this bot only ever simulates *taker* fills, so it
never claims the rebate. Same shape as the tarderz fee model, with the weather rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class FeeModel:
    rate: float = 0.05
    exponent: float = 1.0
    decimals: int = 5
    source: str = "weather_fees (docs.polymarket.com/trading/fees)"

    def fee_per_share(self, price: float) -> float:
        if self.rate <= 0 or not 0.0 < price < 1.0:
            return 0.0
        return self.rate * (price * (1.0 - price)) ** self.exponent

    def match_fee(self, shares: float, price: float) -> float:
        raw = shares * self.fee_per_share(price)
        q = Decimal(1).scaleb(-self.decimals)
        return float(Decimal(repr(raw)).quantize(q, rounding=ROUND_HALF_UP))


WEATHER_FEE = FeeModel()
ZERO_FEE = FeeModel(rate=0.0, source="zero-fee shadow (for comparison only)")
