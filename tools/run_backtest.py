"""Stage 1: tune on the earlier 60% of events, score ONCE on the later 40%.

usage: python tools/run_backtest.py            (tunes on train, then scores test)
       python tools/run_backtest.py --train-only
"""

import itertools
import json
import sys
from collections import defaultdict
from dataclasses import replace
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


def build(elig, meta, cut, df=8.0, include_test=True):
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
        if not include_test and not splits.is_train(e, cut):
            continue  # train-only run: the held-out period is never even prepared
        p = bt.prep_event(e, stations[e["station"]], rm, ALL_DTYPES, df=df)
        if p is None:
            continue
        (train if splits.is_train(e, cut) else test).append(p)
    return train, test


def fmt(s: bt.Summary) -> str:
    return (f"events traded {s.n_events_traded}/{s.n_events_eval}  trades {s.n_trades}  net ${s.net:,.2f}  "
            f"zero-fee ${s.gross:,.2f}  win {100*s.win_rate:.1f}%  per-event ${s.mean_event_pnl:+.3f} "
            f"[{s.ci_event[0]:+.3f},{s.ci_event[1]:+.3f}] date-clustered [{s.ci_date[0]:+.3f},{s.ci_date[1]:+.3f}]")


def tune(train, verbose=True):
    grid = dict(kappa=[1.0, 1.15, 1.3], buffer=[0.04, 0.06, 0.09, 0.12, 0.15], blend=[1.0, 0.7, 0.5, 0.3],
                dtypes=[ALL_DTYPES, ("d3", "d2", "d1"), ("s9", "s11", "s13", "s15")])
    days = sorted({p.day for p in train})
    mid_day = days[len(days) // 2]
    first_half = [p for p in train if p.day < mid_day]
    second_half = [p for p in train if p.day >= mid_day]
    results = []
    for k, b, w, d in itertools.product(grid["kappa"], grid["buffer"], grid["blend"], grid["dtypes"]):
        st = bt.Strategy(kappa=k, buffer=b, blend=w, dtypes=d)
        s = bt.summarize(train, bt.simulate(train, st))
        h1 = bt.summarize(first_half, bt.simulate(first_half, st))
        h2 = bt.summarize(second_half, bt.simulate(second_half, st))
        # score = lower end of the per-event range over all of train, but only if the setting
        # also made money in BOTH the earlier and the later half of the training period
        ok = s.n_events_traded >= 150 and h1.mean_event_pnl > 0 and h2.mean_event_pnl > 0
        score = s.ci_event[0] if ok else -9.0
        results.append((score, st, s))
        if verbose:
            print(f"train kappa={k} buf={b} blend={w} dtypes={','.join(d) if len(d)<7 else 'all'}: {fmt(s)}", flush=True)
    results.sort(key=lambda r: -r[0])
    return results


def report(train, test, best, excluded, cut, out_dir: Path):
    lines = []
    P = lines.append
    tr = bt.simulate(test, best)
    S = bt.summarize(test, tr)
    days = sorted({p.day for p in test})
    last7 = {d for d in days if d > (date.fromisoformat(days[-1]) - timedelta(days=7)).isoformat()}
    idx7 = [i for i, p in enumerate(test) if p.day in last7]
    remap = {old: new for new, old in enumerate(idx7)}
    test7 = [test[i] for i in idx7]
    tr7 = [bt.Trade(**{**t.__dict__, "ev": remap[t.ev]}) for t in tr if t.ev in remap]
    S7 = bt.summarize(test7, tr7)
    P("# Stage 1 results (unseen test period)\n")
    P(f"Chosen settings (picked on the earlier 60% of events only): `{best}`\n")
    P(f"Test period: {days[0]} to {days[-1]} ({len(days)} days with events), {len(test)} events with data; "
      f"cut date between train and test: {cut}\n")
    P("## Headline\n")
    P(f"- Net P&L after 5% taker fees: **${S.net:,.2f}** on {S.n_trades} paper trades in {S.n_events_traded} events "
      f"(${S.cost:,.0f} staked, return on stake {100*S.roi():+.1f}%)")
    P(f"- Same trades with zero fees: ${S.gross:,.2f} (fees cost ${S.fees:,.2f})")
    P(f"- Win rate: {100*S.win_rate:.1f}% of trades")
    P(f"- P&L per traded event: ${S.mean_event_pnl:+.3f}; 95% range ${S.ci_event[0]:+.3f} to ${S.ci_event[1]:+.3f} "
      f"(events resampled), ${S.ci_date[0]:+.3f} to ${S.ci_date[1]:+.3f} (whole days resampled)")
    P(f"- Most recent 7 days: net ${S7.net:,.2f} over {S7.n_events_traded} events\n")
    P("## Pass bar\n")
    checks = bt.passes_bar(S, days, S7)
    for name, ok, detail in checks:
        P(f"- [{'x' if ok else ' '}] {name}: {detail}")
    verdict = all(ok for _, ok, _ in checks)
    P(f"\n**Verdict: {'PASS' if verdict else 'FAIL'}**\n")
    P("## Results by price paid\n")
    P("| price paid | trades | win % | net $ | zero-fee $ | return |\n|---|---|---|---|---|---|")
    for k, n, w, net, g, cost in bt.breakdown(tr, bt.price_bucket):
        P(f"| {k} | {n} | {100*w/n:.0f}% | {net:,.2f} | {g:,.2f} | {100*net/cost:+.1f}% |")
    P("\n## Results by decision time (lead)\n")
    names = {"d3": "2 days before", "d2": "1 day before", "d1": "morning of the day", "s9": "same day 09:00",
             "s11": "same day 11:00", "s13": "same day 13:00", "s15": "same day 15:00"}
    P("| decision | trades | win % | net $ | zero-fee $ | return |\n|---|---|---|---|---|---|")
    for k, n, w, net, g, cost in bt.breakdown(tr, lambda t: t.dtype, order=list(names)):
        P(f"| {names[k]} | {n} | {100*w/n:.0f}% | {net:,.2f} | {g:,.2f} | {100*net/cost:+.1f}% |")
    P("\n## Results by side\n")
    P("| side | trades | win % | net $ | return |\n|---|---|---|---|---|")
    for k, n, w, net, g, cost in bt.breakdown(tr, lambda t: "Buy Yes" if t.side == "Y" else "Buy No"):
        P(f"| {k} | {n} | {100*w/n:.0f}% | {net:,.2f} | {100*net/cost:+.1f}% |")
    P("\n## Baselines (same costs, fees, sizes, limits)\n")
    fav = bt.simulate(test, replace(best, pmin=0.0, pmax=1.0), picker=bt.favourite_picker)
    SF = bt.summarize(test, fav)
    rnd_net, rnd_sd, rnd_pe = bt.random_baseline(test, best, tr)
    P(f"- Strategy: net ${S.net:,.2f}, ${S.mean_event_pnl:+.3f} per traded event")
    P(f"- Always buy the market favourite (Yes): net ${SF.net:,.2f} on {SF.n_trades} trades, ${SF.mean_event_pnl:+.3f} per event "
      f"[{SF.ci_event[0]:+.3f}, {SF.ci_event[1]:+.3f}]")
    P(f"- Random picks (same count per decision time, 20 draws): net ${rnd_net:,.2f} +/- {rnd_sd:,.2f}, ${rnd_pe:+.3f} per event\n")
    P("## Cost sensitivity\n")
    for mode in ("conservative", "typical"):
        sm = bt.summarize(test, bt.simulate(test, replace(best, cost_mode=mode)))
        P(f"- {mode} spread: net ${sm.net:,.2f}, ${sm.mean_event_pnl:+.3f} per event "
          f"[{sm.ci_event[0]:+.3f}, {sm.ci_event[1]:+.3f}] ({sm.n_trades} trades)")
    P("\n## Is the model better than the market? (log-loss on the official winner, lower = better)\n")
    P("| decision | model | market | events |\n|---|---|---|---|")
    ll = bt.log_losses(test, best.kappa)
    for k in names:
        if k in ll:
            P(f"| {names[k]} | {ll[k][0]:.3f} | {ll[k][1]:.3f} | {ll[k][2]} |")
    P("\n## Data notes\n")
    P("Excluded because the airport data could not reproduce Polymarket's official result (rebuilt vs official winner): " +
      ", ".join(f"{k[0]} ({k[1]}) {v[0]}/{v[1]}" for k, v in sorted(excluded.items())) + ".")
    out_dir.mkdir(exist_ok=True)
    (out_dir / "stage1_results.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return verdict


def main() -> None:
    elig, meta, cut, excluded = load_everything()
    print(f"cut date {cut}; usable events {len(elig)}; excluded groups: " +
          ", ".join(f"{k[0]}/{k[1]} ({v[0]}/{v[1]})" for k, v in sorted(excluded.items())))
    train, test = build(elig, meta, cut, include_test="--train-only" not in sys.argv)
    print(f"prepared train {len(train)} events, test {len(test)} events", flush=True)
    results = tune(train)
    best = results[0][1]
    print("\nCHOSEN ON TRAIN:", best, flush=True)
    if "--train-only" in sys.argv:
        return
    report(train, test, best, excluded, cut, Path(__file__).resolve().parent.parent / "reports")


if __name__ == "__main__":
    main()
