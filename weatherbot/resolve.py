"""Rebuild the resolution value (highest reading of the local day, whole degrees) from observations.

Several plausible readings of "highest temperature recorded on this day" exist, so each is a
named variant and `tools/check_resolution.py` scores every variant against Polymarket's
official winners. The variant that reproduces the winners best is the one the model uses.
"""

from __future__ import annotations

import math
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .obs import Obs


def round_half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def standard_offset(tz: str, year: int = 2026) -> timedelta:
    """The station's non-daylight-saving UTC offset (smaller of its January/July offsets)."""
    z = ZoneInfo(tz)
    a = datetime(year, 1, 15, 12, tzinfo=z).utcoffset()
    b = datetime(year, 7, 15, 12, tzinfo=z).utcoffset()
    return min(a, b)


def day_window_utc(tz: str, day: date, basis: str) -> tuple[datetime, datetime]:
    """[start, end) of local `day` in UTC. basis = 'civil' (clock time incl. DST) or 'standard'."""
    if basis == "civil":
        z = ZoneInfo(tz)
        s = datetime.combine(day, time(0), tzinfo=z).astimezone(timezone.utc)
        e = datetime.combine(day + timedelta(days=1), time(0), tzinfo=z).astimezone(timezone.utc)
        return s, e
    off = standard_offset(tz)
    s = datetime.combine(day, time(0), tzinfo=timezone.utc) - off
    return s, s + timedelta(days=1)


def reading(o: Obs, unit: str, how: str) -> float | None:
    """One observation's temperature as a whole number in the event's unit.

    how:
      'tenths' : use the 0.1 degC T-group when present (else the body value), then convert and round
      'body'   : use the whole-degree-C body value, then convert and round
      'iem'    : use IEM's own whole-degree F value (US) / round(T-group C) (elsewhere)
    """
    if how == "body":
        c = o.body_c if o.body_c is not None else o.t_c
    elif how == "tenths":
        c = o.temp_c()
    elif how == "iem":
        if unit == "F" and o.tmpf is not None:
            return float(round_half_up(o.tmpf))
        c = o.temp_c()
    else:
        raise ValueError(how)
    if c is None:
        return None
    return float(round_half_up(c_to_f(c) if unit == "F" else c))


def daily_max(obs: list[Obs], tz: str, day: date, unit: str, *, basis: str = "civil", how: str = "tenths",
              include_special: bool = True) -> tuple[float | None, int]:
    """(max whole-degree reading, number of reports) for the local day."""
    s, e = day_window_utc(tz, day, basis)
    best = None
    n = 0
    for o in obs:
        if o.utc < s or o.utc >= e:
            continue
        if o.is_special and not include_special:
            continue
        v = reading(o, unit, how)
        if v is None:
            continue
        n += 1
        best = v if best is None else max(best, v)
    return best, n


def bracket_index(brackets, value: float) -> int | None:
    """Index of the bracket whose range holds `value` (brackets are dicts or objects with lo/hi)."""
    for i, b in enumerate(brackets):
        lo = b["lo"] if isinstance(b, dict) else b.lo
        hi = b["hi"] if isinstance(b, dict) else b.hi
        if (lo is None or value >= lo) and (hi is None or value <= hi):
            return i
    return None
