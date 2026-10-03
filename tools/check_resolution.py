"""Score every way of rebuilding the daily max against Polymarket's official winners."""

import itertools
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import http, obs, resolve  # noqa: E402


def main() -> None:
    events = json.loads((http.DATA_DIR / "events.json").read_text())
    meta = json.loads((http.DATA_DIR / "stations.json").read_text())
    events = [e for e in events if e["station"] and e["station"] in meta and sum(1 for b in e["brackets"] if (b["final_yes"] or 0) > 0.99) == 1]
    cache: dict[str, list] = {}
    for icao in sorted({e["station"] for e in events}):
        cache[icao] = obs.fetch_obs(icao, date(2025, 12, 28), date(2026, 10, 5))
    variants = list(itertools.product(["civil", "standard"], ["tenths", "body", "iem"], [True, False]))
    score = defaultdict(lambda: [0, 0])  # (variant, group) -> [hits, total]
    for e in events:
        tz = meta[e["station"]]["tz"]
        day = date.fromisoformat(e["target_date"])
        win = next(i for i, b in enumerate(e["brackets"]) if (b["final_yes"] or 0) > 0.99)
        for v in variants:
            basis, how, sp = v
            m, n = resolve.daily_max(cache[e["station"]], tz, day, e["unit"], basis=basis, how=how, include_special=sp)
            ok = m is not None and resolve.bracket_index(e["brackets"], m) == win
            for g in ("ALL", f"{e['source_kind']}/{e['unit']}"):
                score[(v, g)][0] += ok
                score[(v, g)][1] += 1
    groups = sorted({g for _, g in score})
    print(f"{'variant (time basis, reading, specials)':44s}" + "".join(f"{g:>22s}" for g in groups))
    for v in variants:
        line = f"{str(v):44s}"
        for g in groups:
            h, t = score[(v, g)]
            line += f"{100*h/t:>14.1f}% (n={t})" if t else f"{'-':>22s}"
        print(line)


if __name__ == "__main__":
    main()
