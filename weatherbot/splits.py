"""Frozen chronological train/test split.

The cut date is computed ONCE from the list of eligible events (before any result is looked at)
and written to data/split.json. Events dated before the cut are the training set (used to choose
settings); events on or after it are the unseen test set (scored once).
"""

from __future__ import annotations

import json

from . import http

SPLIT_FILE = http.DATA_DIR / "split.json"


def eligible(events: list[dict], stations: dict) -> list[dict]:
    """Events we can actually model: known airport station, exactly one official winner."""
    out = []
    for e in events:
        if not e.get("station") or e["station"] not in stations:
            continue
        if sum(1 for b in e["brackets"] if (b["final_yes"] or 0) > 0.99) != 1:
            continue
        out.append(e)
    return sorted(out, key=lambda e: (e["target_date"], e["event_id"]))


def freeze_split(events: list[dict], train_frac: float = 0.6) -> str:
    if SPLIT_FILE.exists():
        return json.loads(SPLIT_FILE.read_text())["cut_date"]
    cut = events[int(len(events) * train_frac)]["target_date"]
    n_train = sum(1 for e in events if e["target_date"] < cut)
    SPLIT_FILE.write_text(json.dumps({"cut_date": cut, "n_events": len(events), "n_train": n_train,
                                      "n_test": len(events) - n_train, "train_frac": train_frac}))
    return cut


def is_train(e: dict, cut: str) -> bool:
    return e["target_date"] < cut
