"""Loads and aligns everything the backtest needs, with timestamps that make look-ahead visible.

All times are UTC. A "local day" is the station's civil day (clock time incl. daylight saving),
the rule that reproduced Polymarket's official winners best (see tools/check_resolution.py).
"""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import forecast, http, obs as obsmod, prices, resolve, splits

UTC = timezone.utc
HOUR = 3600
OBS_LAG = timedelta(minutes=15)  # a report is treated as visible 15 minutes after its timestamp
OBS_FIRST, OBS_LAST = date(2025, 12, 28), date(2026, 10, 5)  # exactly what tools/collect_obs.py fetched
FINAL_LAG = timedelta(hours=1)  # a finished local day's last report is visible 1 hour after midnight


def ts(dt: datetime) -> float:
    return dt.timestamp()


class StationData:
    """Observations + consensus archived forecasts for one station."""

    def __init__(self, icao: str, meta: dict, unit: str, first: date, last: date):
        self.icao, self.meta, self.unit, self.tz = icao, meta, unit, meta["tz"]
        # fixed archive ranges + offline=True: the backtest never makes a network call
        self.obs = obsmod.fetch_obs(icao, OBS_FIRST, OBS_LAST, offline=True)
        self.obs_ts = [ts(o.utc) for o in self.obs]
        self.obs_c = [o.temp_c() for o in self.obs]
        self.obs_read = [resolve.reading(o, unit, "tenths") for o in self.obs]
        raw = forecast.fetch_previous_runs(meta["lat"], meta["lon"], meta["elevation"],
                                           forecast.ARCHIVE_START, forecast.ARCHIVE_END, offline=True)
        # lead -> epoch-hour -> mean over models; also model count and spread
        self.fc: dict[int, dict[int, float]] = {}
        self.fc_n: dict[int, dict[int, int]] = {}
        for lead in forecast.LEADS:
            acc: dict[int, list[float]] = {}
            for (model, l), series in raw.items():
                if l != lead:
                    continue
                for t, v in series.items():
                    acc.setdefault(int(ts(t)) // HOUR, []).append(v)
            self.fc[lead] = {h: sum(v) / len(v) for h, v in acc.items()}
            self.fc_n[lead] = {h: len(v) for h, v in acc.items()}

    def day_bounds(self, day: date) -> tuple[datetime, datetime]:
        return resolve.day_window_utc(self.tz, day, "civil")

    def obs_between(self, a: datetime, b: datetime) -> range:
        i = bisect.bisect_left(self.obs_ts, ts(a))
        j = bisect.bisect_left(self.obs_ts, ts(b))
        return range(i, j)

    def forecast_remaining(self, lead: int, t: datetime, e: datetime) -> tuple[float | None, int]:
        """Max over hourly forecast values for hours starting in [t, e): (max C, hours counted)."""
        h0 = int(math.ceil(ts(t) / HOUR))
        h1 = int(ts(e) // HOUR)
        vals = [self.fc[lead].get(h) for h in range(h0, h1)]
        got = [v for v in vals if v is not None]
        if not got or len(got) < len(vals):
            return None, len(got)
        return max(got), len(got)

    def observed_so_far(self, s: datetime, t: datetime) -> tuple[float | None, list[int]]:
        """Highest whole-degree reading among reports visible at time t, and their indices."""
        idx = self.obs_between(s, t - OBS_LAG)
        best = None
        for i in idx:
            r = self.obs_read[i]
            if r is not None:
                best = r if best is None else max(best, r)
        return best, list(idx)

    def anomaly(self, lead: int, idx: list[int], n: int = 3) -> float | None:
        """Mean (observed - forecast) over the last n visible reports, in C (None if unavailable)."""
        diffs = []
        for i in reversed(idx):
            c = self.obs_c[i]
            if c is None:
                continue
            h = int(round(self.obs_ts[i] / HOUR))
            f = self.fc[lead].get(h)
            if f is None:
                continue
            diffs.append(c - f)
            if len(diffs) == n:
                break
        return sum(diffs) / len(diffs) if diffs else None

    def truth_remaining_c(self, t: datetime, e: datetime) -> float | None:
        """(training only) highest true temperature C among reports in [t, e)."""
        vals = [self.obs_c[i] for i in self.obs_between(t, e) if self.obs_c[i] is not None]
        return max(vals) if vals else None


@dataclass
class Series:
    """A bracket's midpoint price history."""
    t: list[float]
    p: list[float]

    def at(self, when: float, max_age: float = 2 * HOUR) -> float | None:
        i = bisect.bisect_right(self.t, when) - 1
        if i < 0 or when - self.t[i] > max_age:
            return None
        return self.p[i]


def load_series(e: dict) -> list[Series] | None:
    start = int(datetime.fromisoformat(e["start_date"].replace("Z", "+00:00")).timestamp()) - 3600
    end = int((datetime.fromisoformat(e["end_date"].replace("Z", "+00:00")) + timedelta(hours=48)).timestamp())
    out = []
    for b in e["brackets"]:
        if not http.cached_only(prices.CLOB + "/prices-history", {"market": b["yes_token"], "startTs": start,
                                                                   "endTs": end, "fidelity": 60}):
            return None
        h = prices.price_history(b["yes_token"], start, end, 60)
        out.append(Series([x[0] for x in h], [x[1] for x in h]))
    return out
