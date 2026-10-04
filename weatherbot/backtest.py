"""Honest backtest engine: fills at modelled asks, taker fees, official settlement, clustered CIs.

Look-ahead guards (each one is also covered by tests/):
  * a decision at time T sees only: forecasts public by T (vintage rule in forecast.py), METARs
    timestamped <= T - 15 min, the market midpoint from the last history point at or before T,
    and error statistics learned from days that had fully finished (+1h) before T.
  * the price paid is the MODELLED ASK at time T (midpoint + measured spread), never a close/mid
    from a later time, never the midpoint itself.
  * settlement uses Polymarket's official winning bracket, not the rebuilt temperature.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone

import numpy as np

from . import costs, model
from .dataset import StationData, load_series, ts
from .fees import WEATHER_FEE, ZERO_FEE, FeeModel

KAPPAS = (0.9, 1.0, 1.15, 1.3, 1.5)
MIN_HISTORY_DAYS = 10
PRICE_MAX_AGE = 15 * 60  # refuse a midpoint older than 15 minutes at decision time


@dataclass
class Snap:
    dtype: str
    T: float
    mid: np.ndarray
    mid_norm: np.ndarray
    q: dict  # (kappa) -> np.ndarray of model probabilities
    ask: dict  # cost_mode -> (ask_yes array, ask_no array)
    ask_next: dict  # same, priced off the first midpoint AFTER the decision (pessimistic-fill sensitivity)


@dataclass
class EventPrep:
    ev: dict
    day: str
    win: int
    n: int
    snaps: list[Snap] = field(default_factory=list)


def prep_event(ev: dict, sd: StationData, rm: model.ResidualModel, dtypes, df: float | None = 8.0,
               kappas=KAPPAS) -> EventPrep | None:
    series = load_series(ev)
    if series is None:
        return None
    win = next(i for i, b in enumerate(ev["brackets"]) if (b["final_yes"] or 0) > 0.99)
    day = date.fromisoformat(ev["target_date"])
    prep = EventPrep(ev, ev["target_date"], win, len(ev["brackets"]))
    ticks = [b["tick"] for b in ev["brackets"]]
    for dt in dtypes:
        snap = model.snapshot(sd, day, dt)
        if snap.R is None:
            continue
        T = ts(snap.T)
        mids = [s.at(T, max_age=PRICE_MAX_AGE) for s in series]
        if any(m is None for m in mids):
            continue
        mids = np.array(mids)
        if mids.sum() <= 0:
            continue
        bias, beta, sigma, n_hist = rm.params(sd.icao, dt, snap.T)
        if n_hist < MIN_HISTORY_DAYS:
            continue  # not enough completed days to trust this station's error statistics
        q = {}
        for k in kappas:
            p = model.bracket_probs(ev["brackets"], sd.unit, snap, bias, beta, sigma, kappa=k, df=df)
            if p is None:
                break
            q[k] = np.array(p)
        else:
            nxt = [s.after(T) for s in series]
            mids2 = np.array([a if a is not None else m for a, m in zip(nxt, mids)])
            ask, ask2 = {}, {}
            for mode in ("conservative", "typical"):
                for tgt, mm in ((ask, mids), (ask2, mids2)):
                    ay = np.array([costs.ask_prices(m, tk, mode)[0] for m, tk in zip(mm, ticks)])
                    an = np.array([costs.ask_prices(m, tk, mode)[1] for m, tk in zip(mm, ticks)])
                    tgt[mode] = (ay, an)
            prep.snaps.append(Snap(dt, T, mids, mids / mids.sum(), q, ask, ask2))
    return prep if prep.snaps else None


@dataclass(frozen=True)
class Strategy:
    kappa: float = 1.15
    buffer: float = 0.03
    blend: float = 1.0  # weight on the model (rest on the normalised market midpoint)
    dtypes: tuple = ("d3", "d2", "d1", "s9", "s11", "s13", "s15")
    pmin: float = 0.03
    pmax: float = 0.97
    shares: float = 10.0
    max_pos: int = 3
    max_outlay: float = 25.0
    cost_mode: str = "conservative"
    sides: str = "YN"
    fill: str = "normal"  # "pessimistic" = pay the worse of the ask at T and at the next midpoint


@dataclass
class Trade:
    ev: int
    day: str
    dtype: str
    bracket: int
    side: str
    price: float
    shares: float
    fee: float
    q: float
    edge: float
    won: bool
    pnl: float
    pnl_nofee: float


def _settle(price: float, shares: float, won: bool, fee: float) -> tuple[float, float]:
    gross = shares * ((1.0 if won else 0.0) - price)
    return gross - fee, gross


def simulate(preps: list[EventPrep], st: Strategy, fee_model: FeeModel = WEATHER_FEE, picker=None,
             rng: random.Random | None = None) -> list[Trade]:
    out: list[Trade] = []
    for ei, p in enumerate(preps):
        taken: set[tuple[int, str]] = set()
        outlay = 0.0
        npos = 0
        for s in sorted(p.snaps, key=lambda s: s.T):
            if s.dtype not in st.dtypes:
                continue
            ay, an = s.ask[st.cost_mode]
            if st.fill == "pessimistic":
                ay2, an2 = s.ask_next[st.cost_mode]
                ay, an = np.maximum(ay, ay2), np.maximum(an, an2)
            if picker is None:
                q = st.blend * s.q[st.kappa] + (1.0 - st.blend) * s.mid_norm
                cands = []
                for i in range(p.n):
                    if "Y" in st.sides and st.pmin <= ay[i] <= st.pmax:
                        e = q[i] - ay[i] - fee_model.fee_per_share(ay[i])
                        if e > st.buffer:
                            cands.append((e, i, "Y", q[i]))
                    if "N" in st.sides and st.pmin <= an[i] <= st.pmax:
                        e = (1.0 - q[i]) - an[i] - fee_model.fee_per_share(an[i])
                        if e > st.buffer:
                            cands.append((e, i, "N", 1.0 - q[i]))
                cands.sort(reverse=True)
            else:
                cands = [(0.0, i, side, float("nan")) for i, side in picker(s, p, rng)]
            for e, i, side, qq in cands:
                if npos >= st.max_pos or (i, side) in taken:
                    continue
                price = float(ay[i] if side == "Y" else an[i])
                if outlay + price * st.shares > st.max_outlay:
                    continue
                won = (p.win == i) if side == "Y" else (p.win != i)
                fee = fee_model.match_fee(st.shares, price)
                pnl, gross = _settle(price, st.shares, won, fee)
                out.append(Trade(ei, p.day, s.dtype, i, side, price, st.shares, fee, qq, e, won, pnl, gross))
                taken.add((i, side))
                outlay += price * st.shares
                npos += 1
    return out


# ---------------------------------------------------------------- statistics

def per_event(trades: list[Trade], key: str = "pnl") -> dict[int, float]:
    d: dict[int, float] = {}
    for t in trades:
        d[t.ev] = d.get(t.ev, 0.0) + getattr(t, key)
    return d


def bootstrap_ci(values: np.ndarray, groups: np.ndarray | None = None, n: int = 4000, seed: int = 7):
    """95% interval for the mean of `values`. With `groups`, resamples whole groups (e.g. dates)."""
    rng = np.random.default_rng(seed)
    v = np.asarray(values, float)
    if len(v) == 0:
        return (float("nan"), float("nan"))
    if groups is None:
        idx = rng.integers(0, len(v), size=(n, len(v)))
        means = v[idx].mean(axis=1)
    else:
        uniq, inv = np.unique(groups, return_inverse=True)
        sums = np.bincount(inv, weights=v)
        cnt = np.bincount(inv).astype(float)
        g = rng.integers(0, len(uniq), size=(n, len(uniq)))
        means = sums[g].sum(axis=1) / cnt[g].sum(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


@dataclass
class Summary:
    n_events_eval: int
    n_events_traded: int
    n_trades: int
    net: float
    gross: float  # zero-fee P&L
    fees: float
    win_rate: float
    mean_event_pnl: float
    ci_event: tuple
    ci_date: tuple
    cost: float  # total money put at risk

    def roi(self) -> float:
        return self.net / self.cost if self.cost else float("nan")


def summarize(preps: list[EventPrep], trades: list[Trade], seed: int = 7) -> Summary:
    pe = per_event(trades)
    evs = sorted(pe)
    vals = np.array([pe[e] for e in evs])
    days = np.array([preps[e].day for e in evs])
    net = sum(t.pnl for t in trades)
    gross = sum(t.pnl_nofee for t in trades)
    return Summary(
        n_events_eval=len(preps), n_events_traded=len(evs), n_trades=len(trades), net=net, gross=gross,
        fees=gross - net, win_rate=(sum(t.won for t in trades) / len(trades)) if trades else float("nan"),
        mean_event_pnl=float(vals.mean()) if len(vals) else float("nan"),
        ci_event=bootstrap_ci(vals, None, seed=seed) if len(vals) else (float("nan"),) * 2,
        ci_date=bootstrap_ci(vals, days, seed=seed) if len(vals) else (float("nan"),) * 2,
        cost=sum(t.price * t.shares for t in trades),
    )


def breakdown(trades: list[Trade], keyf, order=None):
    rows: dict = {}
    for t in trades:
        r = rows.setdefault(keyf(t), [0, 0, 0.0, 0.0, 0.0])
        r[0] += 1
        r[1] += int(t.won)
        r[2] += t.pnl
        r[3] += t.pnl_nofee
        r[4] += t.price * t.shares
    keys = order or sorted(rows)
    return [(k, *rows[k]) for k in keys if k in rows]


def price_bucket(t: Trade) -> str:
    for lo, hi in ((0.0, 0.1), (0.1, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)):
        if lo <= t.price < hi:
            return f"{lo:.1f}-{min(hi, 1.0):.1f}"
    return "?"


# ---------------------------------------------------------------- baselines

def favourite_picker(s: Snap, p: EventPrep, rng):
    return [(int(np.argmax(s.mid)), "Y")]


def make_random_picker(rate_by_dtype: dict[str, float]):
    def pick(s: Snap, p: EventPrep, rng: random.Random):
        if rng.random() >= rate_by_dtype.get(s.dtype, 0.0):
            return []
        return [(rng.randrange(p.n), rng.choice("YN"))]
    return pick


def random_baseline(preps, st: Strategy, strat_trades: list[Trade], seeds: int = 20, fee_model=WEATHER_FEE):
    """Random bracket/side picks, as many per decision type as the strategy made. Mean net P&L/event."""
    n_snaps: dict[str, int] = {}
    for p in preps:
        for s in p.snaps:
            if s.dtype in st.dtypes:
                n_snaps[s.dtype] = n_snaps.get(s.dtype, 0) + 1
    made: dict[str, int] = {}
    for t in strat_trades:
        made[t.dtype] = made.get(t.dtype, 0) + 1
    rates = {d: made.get(d, 0) / n_snaps[d] for d in n_snaps}
    nets, per_evt = [], []
    for sd in range(seeds):
        rng = random.Random(1000 + sd)
        tr = simulate(preps, st, fee_model, picker=make_random_picker(rates), rng=rng)
        nets.append(sum(t.pnl for t in tr))
        pe = per_event(tr)
        per_evt.append(sum(pe.values()) / len(pe) if pe else 0.0)
    return float(np.mean(nets)), float(np.std(nets)), float(np.mean(per_evt))


# ---------------------------------------------------------------- model-vs-market scoring

def log_losses(preps: list[EventPrep], kappa: float, dtypes=None):
    """Mean log-loss on the official winner: model vs the market's normalised midpoint (lower is better)."""
    acc: dict[str, list] = {}
    for p in preps:
        for s in p.snaps:
            if dtypes and s.dtype not in dtypes:
                continue
            m = max(float(s.q[kappa][p.win]), 1e-4)
            k = max(float(s.mid_norm[p.win]), 1e-4)
            a = acc.setdefault(s.dtype, [0.0, 0.0, 0])
            a[0] += -math.log(m)
            a[1] += -math.log(k)
            a[2] += 1
    return {d: (a[0] / a[2], a[1] / a[2], a[2]) for d, a in acc.items()}


def passes_bar(test_summary: Summary, test_days: list[str], last_week: Summary) -> list[tuple[str, bool, str]]:
    span = (date.fromisoformat(max(test_days)) - date.fromisoformat(min(test_days))).days + 1
    checks = [
        ("at least 200 traded events in the unseen period", test_summary.n_events_traded >= 200,
         f"{test_summary.n_events_traded} traded events"),
        ("unseen period spans at least 14 days", span >= 14, f"{span} days"),
        ("profitable after fees", test_summary.net > 0, f"net ${test_summary.net:,.2f}"),
        ("per-event 95% range above zero (events resampled)", test_summary.ci_event[0] > 0,
         f"[{test_summary.ci_event[0]:+.3f}, {test_summary.ci_event[1]:+.3f}] per event"),
        ("per-event 95% range above zero (whole days resampled)", test_summary.ci_date[0] > 0,
         f"[{test_summary.ci_date[0]:+.3f}, {test_summary.ci_date[1]:+.3f}] per event"),
        ("still profitable in the most recent 7 days", last_week.net > 0 and last_week.n_events_traded > 0,
         f"net ${last_week.net:,.2f} over {last_week.n_events_traded} events"),
    ]
    return checks
