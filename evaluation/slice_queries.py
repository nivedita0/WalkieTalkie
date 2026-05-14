#!/usr/bin/env python3
"""Create smoke and remaining query files from a base queries.yaml."""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

SMOKE_IDS = [
    "san01", "kol01",  # food
    "san02", "kol02",  # budget
    "san06", "kol06",  # local culture/history
    "san07", "kol07",  # walking route
    "san11", "kol11",  # transit
    "san16", "kol16",  # image
    "san18", "kol18",  # weather
]


def load_queries(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_queries(path: Path, payload: dict) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to queries.yaml")
    parser.add_argument("--out-smoke", required=True, help="Output smoke queries yaml")
    parser.add_argument("--out-rest", required=True, help="Output remaining queries yaml")
    args = parser.parse_args()

    data = load_queries(Path(args.input))
    queries = data.get("queries", [])

    smoke = [q for q in queries if q.get("id") in SMOKE_IDS]
    rest = [q for q in queries if q.get("id") not in SMOKE_IDS]

    meta = data.get("meta", {})

    write_queries(Path(args.out_smoke), {"meta": meta, "queries": smoke})
    write_queries(Path(args.out_rest), {"meta": meta, "queries": rest})

    print(f"Smoke queries: {len(smoke)}")
    print(f"Remaining queries: {len(rest)}")


if __name__ == "__main__":
    main()
