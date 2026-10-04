# Stage 1 verdict: FAIL (do not build the live bot yet)

Paper trading only. No real money, no orders, no keys: this project only reads public data.

## The short answer

The strategy **failed your pass bar** on one of six tests, and the other five passes are less
solid than they look.

| Your test | Result |
|---|---|
| At least 200 events over at least 2 weeks of unseen data | Pass: 2,494 traded events over 81 days (Jul 15 - Oct 3) |
| Profitable after fees | Pass on paper: +$759 on $15,776 staked (+4.8%) |
| Per-event 95% range above zero | Pass: +$0.09 to +$0.53 per event (+$0.04 to +$0.56 resampling whole days) |
| **Still holding in the most recent week** | **FAIL: -$73 over 215 events (Sep 27 - Oct 3)** |

Zero-fee P&L was +$1,154, so fees took $395.

## Why I do not trust the "passes"

These are tests I ran on top of your bar. Each one weakens the headline:

1. **The profit is a handful of lucky events.** The best 5% of events (124) produced 225% of the
   total profit. Without them the strategy lost $947. The typical event loses $1.25, and only 45%
   of events make money. It behaves like buying lottery tickets that occasionally pay.
2. **It does not survive a harsher fill assumption.** History only stores *midpoints*, never real
   asks or order-book depth, so every fill here is modelled (midpoint + the real live spread,
   75th percentile). If I assume you pay the worse of the price now and the price 5 minutes later,
   profit falls from +$759 to +$120 (+$0.05 per event, range -$0.18 to +$0.30, which includes
   zero). With 5-share orders, +$60.
3. **The forecasting part loses money.** Trades made the day before (-$229) or two days before
   (-$116) lost. Nearly all the profit comes from same-day trades at 13:15 (+$432) and 15:15 (+$423),
   when the answer is mostly already known and the market is racing to price new airport readings.
4. **My model is worse than the market.** On the official winner, my probabilities score worse
   than the market's own prices at every decision time (e.g. 1.66 vs 1.38 the day before;
   lower is better). The strategy only made money by leaning 70% on the market price and trading
   rarely, when my model disagreed a lot.
5. **It is fading.** July +4.1%, August +9.2%, September +2.1%, October (3 days) -6.4%.

Baselines (same costs, fees, sizes): always buying the market favourite lost $1,570
(-$0.44 per event); random picks lost $433 (-$0.17 per event). So the market is hard to beat by
simple means and the strategy is better than those, but that is a low bar.

## What I found that differs from the README research

- **NOAA only resolves recent markets.** The `weather.gov` time-series source began on
  **2026-08-23**. Earlier events (Dec 2025 - Aug 2026) resolved on **Weather Underground** airport
  history pages. I handle both.
- **Not always 11 brackets.** Early events (Dec 2025 - Mar 2026) had 7 or 9.
- **Some cities cannot be modelled from airport data.** Hong Kong, Tel Aviv, Istanbul and Moscow
  resolve on their national weather services (790 events). Also excluded, because the airport
  readings could not reproduce Polymarket's official winner: Seoul/RKSI under Weather Underground
  (87% match), Shenzhen under Weather Underground (23%), Jinan (no data), plus three tiny groups.
  On everything kept, my rebuilt daily maximum lands in the official winning bracket 99.3% of
  the time.
- **Price history is the midpoint** of best bid and ask (verified on live books). Real buyers in calm
  hours paid a median of about 1 cent above it; in fast-moving hours much more.
- **Hourly price history was too stale.** Using hourly points made several settings look
  significantly profitable. With 5-minute points, none of 180 tried settings had a 95% range above
  zero on the training period. Everything here uses 5-minute points and refuses any price
  older than 15 minutes.
- **No historical order books exist publicly.** That is the largest uncertainty in this backtest.

## How honest the test was

- Train/test split was **frozen before any results** (cut date 2026-07-15 in `data/split.json`).
- Settings were chosen on training events only (180 candidates; a setting also had to make money in
  both halves of the training period). The test period was scored **once**.
- After seeing *training* diagnostics (never test) I made three fixes: 5-minute prices, a 10-minute
  (not 15-minute) airport-report publication lag, and same-day decisions at HH:15 instead of HH:00
  so the hourly :51 report is visible. These helped the model; the market still beat it.
- Fees: `0.05 * p * (1 - p)` per share, taker only, checked against Polymarket's docs
  (100 shares at 50c = $1.25). Fills at modelled asks, never midpoints. Settlement on Polymarket's
  official result.
- 16 automated tests cover fees, parsing and look-ahead guards (forecast vintage, report
  visibility, price lookups, learning windows, settlement).

## What I would try next (your call)

1. **Do not build the live trading bot yet.** The edge is not demonstrated.
2. **Record real order books going forward** (read-only, no trading) every few minutes for all
   open markets, with airport-report times and forecasts. That removes the biggest unknown (real
   asks and depth) and gives a clean forward test on data nobody has tuned on. A few weeks would
   settle it.
3. **Measure how fast the market reprices after an airport report.** Same-day is the only place
   a model could be fresher than the market. If the market reacts within a few minutes, a bot
   polling from a Windows PC cannot capture it. This can be studied now from the 5-minute data.
4. **Better day-before forecasts** (more or higher-resolution models, ensembles collected live from
   now on). This is a long shot: the market beat my 3-model forecast clearly at every lead time.

Reproduce: `python tools/collect_events.py`, `collect_obs.py`, `collect_forecasts.py`,
`collect_prices.py`, then `python tools/run_backtest.py`. Full tables: `reports/stage1_results.md`.
Fill audit against real trades: `reports/fill_audit.txt`.
