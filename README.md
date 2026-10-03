# Polymarket weather bot (paper only)

Read-only research bot for Polymarket's daily "Highest temperature in <city>"
markets. No real money, no order placement, no keys. Same honesty rules as
polybot: simulated taker fills against the real book, fees included, results
judged after fees with a train/test split.

## Status: paused after research (2026-10-03)

### How the markets work (verified from live Gamma data)
- One event per city per day, e.g. `highest-temperature-in-nyc-on-october-3-2026`,
  tag `daily-temperature`. About 20+ cities a day (NYC, Chicago, Dallas, Miami,
  Atlanta, LA, SF, London, Paris, Madrid, Milan, Munich, Helsinki, Hong Kong,
  Chongqing, Buenos Aires, Sao Paulo, Cape Town, ...).
- 11 mutually exclusive brackets per event (`negRisk: true`), each a Yes/No
  market. US cities in °F with 2-degree brackets (e.g. "62-63°F", "61°F or
  below", "80°F or higher"); other cities in °C with 1-degree brackets.
- Resolution: the highest reading in the "Temp" column of NOAA's hourly data
  for one airport station on that local day, whole degrees. The station is in
  `resolutionSource`, e.g. https://www.weather.gov/wrh/timeseries?site=klga
  (NYC = LaGuardia), site=eglc (London City). Fallback: Weather Underground.
  It uses the hourly data ("Show Hourly Data"), so the true peak between
  hourly reports may not count.
- Resolves when the next day's first data point is published, or by 11:59 PM
  ET the following day.
- Fees: `weather_fees`, rate 0.05, exponent 1, taker only; makers get a 25%
  rebate. Fee per share = 0.05 * p * (1 - p).
- By the afternoon of the day itself the answer is mostly known (NYC's
  70-71°F bracket was at 99.5c), so any edge is earlier: the day before, or
  intraday using the observations so far ("the max can't be below what's
  already been recorded").

### Data sources (reachability checked)
| source | use | status |
|---|---|---|
| api.open-meteo.com `/v1/forecast` | live deterministic forecasts | OK, no key |
| ensemble-api.open-meteo.com `/v1/ensemble` | live ensemble members -> bracket probabilities | OK, no key |
| previous-runs-api / historical-forecast-api.open-meteo.com | past forecasts for a fair backtest | rate-limited (daily limit hit from the shared IP); retry |
| mesonet.agron.iastate.edu ASOS archive | historical airport observations (METAR), worldwide | OK |
| api.weather.gov stations/observations | live US observations | OK (needs User-Agent) |
| aviationweather.gov `/api/data/metar` | live METAR, worldwide | OK |
| api.synopticdata.com | NOAA timeseries backend | needs a token (401); not used |
| gamma-api / clob.polymarket.com prices-history | markets, rules, price history | OK |

### Plan
1. Model: ensemble daily-max distribution at the station (local day), bias
   correction per station from history, dressed with an error kernel, rounded
   the way the resolution source rounds, converted to bracket probabilities.
   Same-day: condition on the max observed so far (METAR).
2. Backtest first: resolved past events (Gamma), Polymarket price history per
   bracket, past forecasts at the matching lead time, 5% fee formula, settle
   on the official bracket. Choose settings on the earlier 60%, score on the
   later 40%. Only build the live bot if this passes.
3. Live paper bot: discovery, forecasts, order-book polling (weather markets
   are slow), paper fills, settlement, report, small dashboard, daily archive.
4. Windows one-line installer and desktop shortcut, like polybot.
