"""Airport observations (METAR) from the Iowa State Mesonet archive.

We use routine hourly METARs and SPECIs (report_type 3 and 4). The raw METAR text is kept
so the temperature can be read three ways:
  * body_c  : whole degrees C in the main body ("19/12" -> 19)  - what the report headline says
  * t_c     : tenths of a degree C from the RMK T-group ("T01940122" -> 19.4)
  * tmpf    : IEM's own whole-degree F value (derived from the T-group when present)
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from . import http

ASOS = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

_BODY = re.compile(r"\s(M?\d{2})/(?:M?\d{2}|//)?\s")
_TGRP = re.compile(r"\sT([01])(\d{3})([01])(\d{3})\b")


@dataclass(frozen=True)
class Obs:
    utc: datetime
    body_c: float | None
    t_c: float | None
    tmpf: float | None
    is_special: bool
    raw: str

    def temp_c(self) -> float | None:
        return self.t_c if self.t_c is not None else self.body_c


def _parse_c(tok: str) -> float:
    return -float(tok[1:]) if tok.startswith("M") else float(tok)


def parse_metar_temp(raw: str) -> tuple[float | None, float | None]:
    body = None
    if m := _BODY.search(raw):
        try:
            body = _parse_c(m[1])
        except ValueError:
            body = None
    t = None
    if m := _TGRP.search(raw):
        t = int(m[2]) / 10.0
        if m[1] == "1":
            t = -t
    return body, t


def _month_chunks(start: date, end: date):
    """Calendar-month chunks (start inclusive, end exclusive) covering [start, end)."""
    d = date(start.year, start.month, 1)
    while d < end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        yield max(d, start), min(nxt, end)
        d = nxt


def fetch_obs(icao: str, start: date, end: date) -> list[Obs]:
    """All routine+special METARs for `icao` with UTC time in [start, end)."""
    iem_id = icao[1:] if icao.startswith("K") and len(icao) == 4 else icao
    out: list[Obs] = []
    for a, b in _month_chunks(start, end):
        params = [
            ("station", iem_id),
            ("data", "tmpf"),
            ("data", "metar"),
            ("year1", a.year), ("month1", a.month), ("day1", a.day),
            ("year2", b.year), ("month2", b.month), ("day2", b.day),
            ("tz", "UTC"), ("format", "onlycomma"), ("latlon", "no"),
            ("missing", "M"), ("trace", "T"), ("direct", "no"),
            ("report_type", 3), ("report_type", 4),
        ]
        text = http.get(ASOS, params, as_text=True)  # list of tuples handled by requests
        out.extend(_parse_csv(text))
    out.sort(key=lambda o: o.utc)
    return out


def _parse_csv(text: str) -> list[Obs]:
    rows = csv.DictReader(io.StringIO(text))
    res: list[Obs] = []
    for r in rows:
        v = r.get("valid")
        raw = r.get("metar") or ""
        if not v or not raw or "MADISHF" in raw:
            continue
        try:
            ts = datetime.strptime(v, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        body, t = parse_metar_temp(raw)
        try:
            tf = float(r["tmpf"]) if r.get("tmpf") not in (None, "", "M") else None
        except ValueError:
            tf = None
        if body is None and t is None and tf is None:
            continue
        res.append(Obs(ts, body, t, tf, raw.lstrip().startswith("SPECI"), raw))
    return res
