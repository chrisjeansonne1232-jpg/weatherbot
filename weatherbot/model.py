"""Probability model: P(each bracket wins) from archived forecasts + observations so far.

Idea (all temperatures in C internally):
    final reading = max( highest reading already published,  highest reading from now to local midnight )
    highest reading from now on  ~  forecast_remaining_max + bias + beta * (current obs - forecast anomaly)
                                    + noise(sigma),   noise ~ Student-t (or normal)
    bias, sigma are learned per station and decision type from RECENT PAST DAYS ONLY, shrunk toward the
    pooled value across stations when a station has little history.
Rounding matches the resolution: each report is rounded to a whole degree in the event's unit, so
P(final <= k) uses the threshold k + 0.5 (converted to C for Fahrenheit events).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np
from scipy.stats import norm, t as student_t

from . import resolve
from .dataset import FINAL_LAG, StationData, ts

# decision type -> (forecast vintage in days, hours after local midnight)
DECISIONS: dict[str, tuple[int, int]] = {
    "d3": (3, -41),  # ~2 days before the local day, earliest legal time for 3-day-old runs
    "d2": (2, -17),  # the day before
    "d1": (1, 7),  # morning of the day
    "s9": (1, 9),
    "s11": (1, 11),
    "s13": (1, 13),
    "s15": (1, 15),
}
DEFAULT_SIGMA = {"d3": 2.4, "d2": 2.0, "d1": 1.6, "s9": 1.4, "s11": 1.1, "s13": 0.8, "s15": 0.5}
WINDOW_DAYS = 45
PRIOR_K = 8.0  # pseudo-observations of the pooled value mixed into each station's estimate
MIN_POOL = 60


@dataclass
class Snap:
    T: datetime  # decision time
    S: datetime  # local day start
    E: datetime  # local day end
    R: float | None  # forecast max over the remaining hours (C)
    M: float | None  # highest whole-degree reading visible at T (event unit)
    A: float | None  # recent observed-minus-forecast anomaly (C)
    n_hours: int


def snapshot(sd: StationData, day: date, dtype: str) -> Snap:
    lead, off = DECISIONS[dtype]
    S, E = sd.day_bounds(day)
    T = S + timedelta(hours=off)
    start = max(T, S)
    R, nh = sd.forecast_remaining(lead, start, E)
    M, idx = (None, [])
    if T > S:
        M, idx = sd.observed_so_far(S, T)
    A = sd.anomaly(lead, idx) if idx else None
    return Snap(T, S, E, R, M, A, nh)


@dataclass
class Row:
    E: datetime
    r: float  # true remaining max minus forecast remaining max (C)
    A: float


class ResidualModel:
    """Learns per-station, per-decision-type error statistics, causally."""

    def __init__(self, stations: dict[str, StationData]):
        self.stations = stations
        self.rows: dict[tuple[str, str], list[Row]] = {}
        self._pool_cache: dict[tuple[str, date], tuple[float, float, float, int]] = {}

    def _build(self, icao: str, dtype: str) -> list[Row]:
        sd = self.stations[icao]
        if not sd.obs:
            return []
        rows: list[Row] = []
        first = datetime.fromtimestamp(sd.obs_ts[0], tz=sd.obs[0].utc.tzinfo).date() + timedelta(days=2)
        last = datetime.fromtimestamp(sd.obs_ts[-1], tz=sd.obs[0].utc.tzinfo).date() - timedelta(days=2)
        d = first
        while d <= last:
            snap = snapshot(sd, d, dtype)
            if snap.R is not None:
                Y = sd.truth_remaining_c(max(snap.T, snap.S), snap.E)
                if Y is not None:
                    rows.append(Row(snap.E, Y - snap.R, snap.A if snap.A is not None else 0.0))
            d += timedelta(days=1)
        return rows

    def table(self, icao: str, dtype: str) -> list[Row]:
        k = (icao, dtype)
        if k not in self.rows:
            self.rows[k] = self._build(icao, dtype)
        return self.rows[k]

    def _window(self, icao: str, dtype: str, T: datetime) -> list[Row]:
        lo = T - timedelta(days=WINDOW_DAYS)
        hi = T - FINAL_LAG
        return [r for r in self.table(icao, dtype) if lo <= r.E <= hi]

    def _pool(self, dtype: str, T: datetime) -> tuple[float, float, float, int]:
        """(bias, beta, sigma, n) pooled over all stations, using only rows visible a day earlier."""
        cutoff_day = (T - FINAL_LAG).date()
        key = (dtype, cutoff_day)
        if key in self._pool_cache:
            return self._pool_cache[key]
        hi = datetime.combine(cutoff_day, datetime.min.time(), tzinfo=T.tzinfo)
        lo = hi - timedelta(days=WINDOW_DAYS)
        rs, As, grp = [], [], []
        for icao in self.stations:
            for row in self.table(icao, dtype):
                if lo <= row.E <= hi:
                    rs.append(row.r)
                    As.append(row.A)
                    grp.append(icao)
        n = len(rs)
        if n < MIN_POOL:
            out = (0.0, 0.0, DEFAULT_SIGMA[dtype], n)
        else:
            r = np.array(rs)
            A = np.array(As)
            g = np.array(grp)
            # demean within station so station bias does not leak into beta
            rd, Ad = r.copy(), A.copy()
            for s in set(grp):
                m = g == s
                rd[m] -= r[m].mean()
                Ad[m] -= A[m].mean()
            beta = float((rd * Ad).sum() / max((Ad * Ad).sum(), 1e-9)) if dtype.startswith("s") else 0.0
            beta = max(0.0, min(beta, 1.0))
            bias = float(r.mean() - beta * A.mean())
            e = r - bias - beta * A
            out = (bias, beta, float(max(e.std(), 0.25)), n)
        self._pool_cache[key] = out
        return out

    def params(self, icao: str, dtype: str, T: datetime) -> tuple[float, float, float, int]:
        """(bias, beta, sigma, n_days) for a decision at time T using only data visible before T."""
        pb, beta, ps, pn = self._pool(dtype, T)
        rows = self._window(icao, dtype, T)
        n = len(rows)
        if n == 0:
            return pb, beta, ps, 0
        r = np.array([x.r for x in rows])
        A = np.array([x.A for x in rows])
        bias = (float((r - beta * A).sum()) + PRIOR_K * pb) / (n + PRIOR_K)
        e = r - bias - beta * A
        var = (float((e * e).sum()) + PRIOR_K * ps * ps) / (n + PRIOR_K)
        return bias, beta, math.sqrt(max(var, 0.0625)), n


def threshold_c(k: float, unit: str) -> float:
    """C value separating reading k from k+1 (readings are whole degrees in `unit`)."""
    return resolve.f_to_c(k + 0.5) if unit == "F" else k + 0.5


def bracket_probs(brackets, unit: str, snap: Snap, bias: float, beta: float, sigma: float, *,
                  kappa: float = 1.0, df: float | None = 8.0) -> list[float] | None:
    """P(bracket contains the final reading) for each bracket (they sum to 1)."""
    if snap.R is None:
        return None
    A = snap.A if snap.A is not None else 0.0
    mu = snap.R + bias + beta * A
    scale = max(sigma * kappa, 0.15)

    def val(b, key):
        return b[key] if isinstance(b, dict) else getattr(b, key)

    # every distinct "final <= k" threshold the brackets need, evaluated in one vectorised call
    ks = sorted({val(b, "hi") for b in brackets if val(b, "hi") is not None}
                | {val(b, "lo") - 1 for b in brackets if val(b, "lo") is not None})
    x = np.array([threshold_c(k, unit) for k in ks])
    z = (x - mu) / scale
    cdf = norm.cdf(z) if df is None else student_t.cdf(z * math.sqrt(df / (df - 2.0)), df)
    F = {}
    for k, c in zip(ks, cdf):
        F[k] = 0.0 if (snap.M is not None and snap.M > k) else float(c)
    out = []
    for b in brackets:
        hi, lo = val(b, "hi"), val(b, "lo")
        top = 1.0 if hi is None else F[hi]
        bot = 0.0 if lo is None else F[lo - 1]
        out.append(max(top - bot, 0.0))
    tot = sum(out)
    return [v / tot for v in out] if tot > 0 else None
