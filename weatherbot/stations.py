"""Station metadata (coordinates, timezone) from the Iowa State Mesonet station API."""

from __future__ import annotations

from dataclasses import dataclass

from . import http

IEM_STATION = "https://mesonet.agron.iastate.edu/api/1/station/{id}.json"


@dataclass(frozen=True)
class Station:
    icao: str
    name: str
    lat: float
    lon: float
    tz: str
    elevation: float
    network: str


def _score(row: dict) -> int:
    net = (row.get("network") or "").upper()
    s = 0
    if net.endswith("_ASOS") or net.endswith("_AWOS"):
        s += 10  # the real airport observation network
    if row.get("tzname"):
        s += 2
    if row.get("latitude") is not None:
        s += 1
    return s


def get_station(icao: str) -> Station:
    ids = [icao]
    if icao.startswith("K") and len(icao) == 4:
        ids.append(icao[1:])  # IEM lists many US airports under the 3-letter code
    rows: list[dict] = []
    for i in ids:
        try:
            d = http.get(IEM_STATION.format(id=i))
        except http.FetchError:
            continue
        rows = d.get("data") or []
        if rows and any((r.get("network") or "").upper().endswith(("_ASOS", "_AWOS")) for r in rows):
            break
    if not rows:
        raise KeyError(f"IEM has no metadata for {icao}")
    row = max(rows, key=_score)
    if not row.get("tzname"):
        raise KeyError(f"IEM metadata for {icao} lacks a timezone")
    return Station(
        icao=icao,
        name=row.get("name") or icao,
        lat=float(row["latitude"]),
        lon=float(row["longitude"]),
        tz=row["tzname"],
        elevation=float(row.get("elevation") or 0.0),
        network=row.get("network") or "",
    )
