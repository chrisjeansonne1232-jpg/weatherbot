"""Data-integrity filter: which (station, resolution source) groups can be rebuilt from METARs?

A group is usable if the reconstructed daily maximum lands in Polymarket's OFFICIAL winning bracket
at least `MIN_AGREEMENT` of the time. This looks only at resolutions (not at any trading result).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from . import obs, resolve

MIN_AGREEMENT = 0.90
MIN_EVENTS = 12


def agreement(events: list[dict], meta: dict) -> dict[tuple[str, str], tuple[int, int]]:
    cache: dict[str, list] = {}
    out: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for e in events:
        st = e["station"]
        if st not in cache:
            cache[st] = obs.fetch_obs(st, date(2025, 12, 28), date(2026, 10, 5), offline=True)
        win = next(i for i, b in enumerate(e["brackets"]) if (b["final_yes"] or 0) > 0.99)
        m, _ = resolve.daily_max(cache[st], meta[st]["tz"], date.fromisoformat(e["target_date"]), e["unit"])
        ok = m is not None and resolve.bracket_index(e["brackets"], m) == win
        g = out[(st, e["source_kind"])]
        g[0] += int(ok)
        g[1] += 1
    return {k: (v[0], v[1]) for k, v in out.items()}


def usable_groups(events: list[dict], meta: dict) -> tuple[set[tuple[str, str]], dict]:
    ag = agreement(events, meta)
    good = {k for k, (h, n) in ag.items() if n >= MIN_EVENTS and h / n >= MIN_AGREEMENT}
    return good, ag
