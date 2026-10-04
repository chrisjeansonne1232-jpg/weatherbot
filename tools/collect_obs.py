"""Step 2: download routine+special METARs for every resolution station (cached, monthly chunks)."""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from weatherbot import dataset, http, obs  # noqa: E402


def main() -> None:
    meta = json.loads((http.DATA_DIR / "stations.json").read_text())
    start, end = dataset.OBS_FIRST, dataset.OBS_LAST
    for i, icao in enumerate(sorted(meta), 1):
        rows = obs.fetch_obs(icao, start, end)
        print(f"[{i}/{len(meta)}] {icao}: {len(rows)} reports", flush=True)


if __name__ == "__main__":
    main()
