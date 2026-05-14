#!/usr/bin/env python3
"""Summarize evaluation JSONL files by tier."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    k = (len(values) - 1) * (pct / 100.0)
    f = int(k)
    c = min(f + 1, len(values) - 1)
    if f == c:
        return values[f]
    d0 = values[f] * (c - k)
    d1 = values[c] * (k - f)
    return d0 + d1


def load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def summarize(rows: list[dict]) -> dict:
    tiers = {"small": [], "large": []}
    errors = {"small": 0, "large": 0}
    for r in rows:
        tier = r.get("tier")
        if tier not in tiers:
            continue
        elapsed = float(r.get("elapsed_sec", -1))
        tiers[tier].append(elapsed)
        if elapsed < 0:
            errors[tier] += 1

    summary: dict[str, dict[str, float]] = {}
    for tier, vals in tiers.items():
        valid = [v for v in vals if v >= 0]
        summary[tier] = {
            "count": float(len(vals)),
            "mean": mean(valid) if valid else 0.0,
            "p50": percentile(valid, 50),
            "p90": percentile(valid, 90),
            "error_rate": (errors[tier] / len(vals)) if vals else 0.0,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to eval JSONL")
    parser.add_argument("--out", required=True, help="Output summary json")
    args = parser.parse_args()

    rows = load_rows(Path(args.input))
    summary = summarize(rows)
    Path(args.out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
