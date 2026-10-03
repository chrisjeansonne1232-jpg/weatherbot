"""Stage 1: tune on the earlier 60% of events, score ONCE on the later 40%.

usage: python tools/run_backtest.py            (tunes on train, then scores test)
       python tools/run_backtest.py --train-only
"""

import itertools
import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import backtest as bt  # noqa: E402
from weatherbot import dataset, http, model, quality, splits  # noqa: E402

ALL_DTYPES = tuple(model.DECISIONS)


def load_everything():
    events = json.loads((http.DATA_DIR / "events.json").read_text())
    meta = json.loads((http.DATA_DIR / "stations.json").read_text())
    elig = splits.eligible(events, meta)
    good, ag = quality.usable_groups(elig, meta)
    excluded = {k: v for k, v in ag.items() if k not in good}
    elig = [e for e in elig if (e["station"], e["source_kind"]) in good]
    cut = splits.freeze_split(splits.eligible(events, meta))  # frozen BEFORE the quality filter
    return elig, meta, cut, excluded


def build(elig, meta, cut, df=8.0):
    first = date.fromisoformat(min(e["target_date"] for e in elig))
    last = date.fromisoformat(max(e["target_date"] for e in elig))
    units = {}
    for e in elig:
        units[e["station"]] = e["unit"]
    stations = {}
    for icao in sorted(units):
        stations[icao] = dataset.StationData(icao, meta[icao], units[icao], first, last)
    rm = model.ResidualModel(stations)
    train, test = [], []
    for e in elig:
        p = bt.prep_event(e, stations[e["station"]], rm, ALL_DTYPES, df=df)
        if p is None:
            continue
        (train if splits.is_train(e, cut) else test).append(p)
    return train, test


def fmt(s: bt.Summary) -> str:
    return (f"events traded {s.n_events_traded}/{s.n_events_eval}  trades {s.n_trades}  net ${s.net:,.2f}  "
            f"zero-fee ${s.gross:,.2f}  win {100*s.win_rate:.1f}%  per-event ${s.mean_event_pnl:+.3f} "
            f"[{s.ci_event[0]:+.3f},{s.ci_event[1]:+.3f}] date-clustered [{s.ci_date[0]:+.3f},{s.ci_date[1]:+.3f}]")


def main() -> None:
    elig, meta, cut, excluded = load_everything()
    print(f"cut date {cut}; usable events {len(elig)}; excluded groups: " +
          ", ".join(f"{k[0]}/{k[1]} ({v[0]}/{v[1]})" for k, v in sorted(excluded.items())))
    train, test = build(elig, meta, cut)
    print(f"prepared train {len(train)} events, test {len(test)} events")
    # model quality: log loss of model vs market at each decision type (train only)
    grid = dict(kappa=[1.0, 1.15, 1.3], buffer=[0.02, 0.04, 0.06, 0.09], blend=[1.0, 0.7],
                dtypes=[ALL_DTYPES, ("d3", "d2", "d1"), ("s9", "s11", "s13", "s15")])
    results = []
    for k, b, w, d in itertools.product(grid["kappa"], grid["buffer"], grid["blend"], grid["dtypes"]):
        st = bt.Strategy(kappa=k, buffer=b, blend=w, dtypes=d)
        tr = bt.simulate(train, st)
        s = bt.summarize(train, tr)
        score = s.mean_event_pnl - (s.mean_event_pnl - s.ci_event[0]) if s.n_events_traded >= 150 else -9
        results.append((score, st, s))
        print(f"train k={k} buf={b} blend={w} dt={len(d)}: {fmt(s)}", flush=True)
    results.sort(key=lambda r: -r[0])
    best = results[0][1]
    print("\nCHOSEN ON TRAIN:", best)
    if "--train-only" in sys.argv:
        return
    tr = bt.simulate(test, best)
    print("\nTEST (unseen):", fmt(bt.summarize(test, tr)))


if __name__ == "__main__":
    main()
