"""Archived NWP forecasts from Open-Meteo's Previous Runs API (free, no key).

`temperature_2m_previous_dayN` for valid hour H is "the value predicted N*24 hours before H"
(docs: open-meteo.com/en/docs/previous-runs-api). That makes the vintage explicit, which is what
lets the backtest avoid look-ahead:

    a run initialised at time I is public from about I + PUBLISH_DELAY_H.
    previous_dayN for hour H comes from a run initialised at or before H - 24N hours.
    => for a local day starting at S (last hour S+23h), all previous_dayN values are public by
       S + 23h - 24N*h + PUBLISH_DELAY_H.  That is the earliest legal decision time for vintage N.

We never use previous_day0 ("current run"), because its availability is not defined by lead time.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from . import http

PREV = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_START = date(2025, 12, 27)  # fixed so every caller hits the same cache chunks
ARCHIVE_END = date(2026, 10, 4)
MODELS = ("ecmwf_ifs025", "gfs_seamless", "icon_seamless")
LEADS = (1, 2, 3)
PUBLISH_DELAY_H = 8  # conservative: runs are normally public 4-7 hours after initialisation

_KEY = re.compile(r"^temperature_2m_previous_day(\d)(?:_(.+))?$")


def earliest_decision_utc(day_start_utc: datetime, lead_days: int) -> datetime:
    """Earliest UTC time at which every hour of the local day has its previous_day{lead_days} value."""
    return day_start_utc + timedelta(hours=23 - 24 * lead_days + PUBLISH_DELAY_H)


def _chunks(start: date, end: date, days: int = 92):
    d = start
    while d <= end:
        e = min(d + timedelta(days=days - 1), end)
        yield d, e
        d = e + timedelta(days=1)


def fetch_previous_runs(lat: float, lon: float, elevation: float, start: date, end: date,
                        models=MODELS, leads=LEADS, offline: bool = False) -> dict[tuple[str, int], dict[datetime, float]]:
    """{(model, lead_days): {utc_hour: temp_C}} for [start, end] (inclusive)."""
    out: dict[tuple[str, int], dict[datetime, float]] = {}
    for a, b in _chunks(start, end):
        d = http.get(PREV, {
            "latitude": round(lat, 4), "longitude": round(lon, 4), "elevation": round(elevation),
            "hourly": ",".join(f"temperature_2m_previous_day{n}" for n in leads),
            "models": ",".join(models), "start_date": a.isoformat(), "end_date": b.isoformat(),
            "timezone": "UTC", "temperature_unit": "celsius",
        }, offline=offline)
        h = d["hourly"]
        times = [datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in h["time"]]
        for k, vals in h.items():
            m = _KEY.match(k)
            if not m:
                continue
            lead = int(m[1])
            model = m[2] or models[0]
            tgt = out.setdefault((model, lead), {})
            for t, v in zip(times, vals):
                if v is not None:
                    tgt[t] = float(v)
    return out
