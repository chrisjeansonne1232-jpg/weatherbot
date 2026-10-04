"""Step 4: archived forecasts (3 models x leads 1-3 days) at every station. Slow and cached on purpose."""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import forecast, http  # noqa: E402


def main() -> None:
    meta = json.loads((http.DATA_DIR / "stations.json").read_text())
    skip = set(sys.argv[1:])  # stations to skip
    start, end = forecast.ARCHIVE_START, forecast.ARCHIVE_END
    for i, icao in enumerate(sorted(meta), 1):
        if icao in skip:
            continue
        s = meta[icao]
        try:
            data = forecast.fetch_previous_runs(s["lat"], s["lon"], s["elevation"], start, end)
        except http.RateLimited as e:
            print("STOP: rate limited:", e, flush=True)
            sys.exit(2)
        print(f"[{i}/{len(meta)}] {icao}: " + ", ".join(f"{m}/d{l}={len(v)}" for (m, l), v in sorted(data.items())), flush=True)


if __name__ == "__main__":
    main()
