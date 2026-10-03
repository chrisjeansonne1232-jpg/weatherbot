"""Gamma (market metadata) access and parsing of daily-temperature events."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import http

GAMMA = "https://gamma-api.polymarket.com"
TAG = "daily-temperature"


@dataclass
class Bracket:
    market_id: str
    condition_id: str
    title: str  # e.g. "62-63°F", "61°F or below", "80°F or higher", "17°C"
    lo: float | None  # inclusive lower bound in whole degrees (None = open below)
    hi: float | None  # inclusive upper bound (None = open above)
    yes_token: str
    no_token: str
    final_yes: float | None  # official settlement price of Yes (1.0 / 0.0) once resolved
    volume: float
    tick: float
    min_size: float
    closed_time: str | None


@dataclass
class TempEvent:
    event_id: str
    slug: str
    title: str
    city: str
    target_date: str  # YYYY-MM-DD, the local day the market is about
    unit: str  # "F" or "C"
    station: str | None  # ICAO, upper case, from resolutionSource
    resolution_source: str
    source_kind: str
    start_date: str  # when trading opened (ISO, UTC)
    end_date: str
    description: str
    closed: bool
    brackets: list[Bracket] = field(default_factory=list)

    @property
    def winner(self) -> Bracket | None:
        w = [b for b in self.brackets if b.final_yes is not None and b.final_yes > 0.99]
        return w[0] if len(w) == 1 else None

    @property
    def n_winners(self) -> int:
        return sum(1 for b in self.brackets if b.final_yes is not None and b.final_yes > 0.99)


_RANGE = re.compile(r"^\s*(-?\d+)\s*[-–]\s*(-?\d+)\s*°\s*([FC])", re.I)
_BELOW = re.compile(r"^\s*(-?\d+)\s*°\s*([FC])\s*or\s*(below|lower|less)", re.I)
_ABOVE = re.compile(r"^\s*(-?\d+)\s*°\s*([FC])\s*or\s*(higher|above|more)", re.I)
_SINGLE = re.compile(r"^\s*(-?\d+)\s*°\s*([FC])\s*$", re.I)


def parse_bracket_title(t: str):
    """'62-63°F' -> (62, 63, 'F'); '61°F or below' -> (None, 61, 'F'); '80°F or higher' -> (80, None, 'F')."""
    if m := _RANGE.match(t):
        return float(m[1]), float(m[2]), m[3].upper()
    if m := _BELOW.match(t):
        return None, float(m[1]), m[2].upper()
    if m := _ABOVE.match(t):
        return float(m[1]), None, m[2].upper()
    if m := _SINGLE.match(t):
        return float(m[1]), float(m[1]), m[2].upper()
    return None


_SITE = re.compile(r"[?&]site=([A-Za-z0-9]+)", re.I)
_CITY = re.compile(r"highest temperature in (.+?) on ", re.I)


_WU = re.compile(r"wunderground\.com/history/daily/(?:[^/]+/)+([A-Za-z0-9]{4})/?(?:[?#].*)?$", re.I)


def station_from_source(url: str) -> str | None:
    """ICAO code of the resolution station.

    NOAA time-series URLs carry ?site=klga; Weather Underground history URLs end in the ICAO code.
    """
    u = url or ""
    if m := _SITE.search(u):
        return m[1].upper()
    if m := _WU.search(u):
        return m[1].upper()
    return None


def source_kind(url: str) -> str:
    u = (url or "").lower()
    if "weather.gov/wrh" in u:
        return "noaa_wrh"
    if "wunderground.com" in u:
        return "wunderground"
    return "other" if u else "none"


def parse_event(e: dict) -> TempEvent | None:
    title = e.get("title") or ""
    cm = _CITY.search(title)
    if not cm or not e.get("markets"):
        return None
    brackets: list[Bracket] = []
    unit = None
    for m in e["markets"]:
        gt = m.get("groupItemTitle") or ""
        pb = parse_bracket_title(gt)
        if pb is None:
            return None
        lo, hi, u = pb
        unit = unit or u
        try:
            toks = json.loads(m.get("clobTokenIds") or "[]")
            prices = json.loads(m.get("outcomePrices") or "[]")
        except json.JSONDecodeError:
            return None
        if len(toks) != 2:
            return None
        final_yes = float(prices[0]) if prices and m.get("closed") else None
        brackets.append(
            Bracket(
                market_id=str(m["id"]),
                condition_id=m["conditionId"],
                title=gt,
                lo=lo,
                hi=hi,
                yes_token=toks[0],
                no_token=toks[1],
                final_yes=final_yes,
                volume=float(m.get("volumeNum") or m.get("volume") or 0),
                tick=float(m.get("orderPriceMinTickSize") or 0.01),
                min_size=float(m.get("orderMinSize") or 5),
                closed_time=m.get("closedTime"),
            )
        )
    brackets.sort(key=lambda b: (b.lo if b.lo is not None else -1e9))
    target = (e.get("endDate") or "")[:10]
    return TempEvent(
        event_id=str(e["id"]),
        slug=e.get("slug") or "",
        title=title,
        city=cm[1].strip(),
        target_date=target,
        unit=unit or "?",
        station=station_from_source(e.get("resolutionSource") or ""),
        resolution_source=e.get("resolutionSource") or "",
        source_kind=source_kind(e.get("resolutionSource") or ""),
        start_date=e.get("startDate") or "",
        end_date=e.get("endDate") or "",
        description=e.get("description") or "",
        closed=bool(e.get("closed")),
        brackets=brackets,
    )


def fetch_event_pages(closed: bool = True, page: int = 100, max_pages: int = 500):
    """Yield raw event dicts for every event carrying the daily-temperature tag.

    Uses keyset pagination: plain offset paging is refused by Gamma past ~2,100 rows.
    """
    cursor = None
    for _ in range(max_pages):
        params = {
            "tag_slug": TAG,
            "closed": "true" if closed else "false",
            "limit": page,
            "order": "endDate",
            "ascending": "true",
        }
        if cursor:
            params["after_cursor"] = cursor
        data = http.get(GAMMA + "/events/keyset", params)
        events = data.get("events") or []
        yield from events
        cursor = data.get("next_cursor")
        if not cursor or not events:
            return
