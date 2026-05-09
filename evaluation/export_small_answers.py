#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import argparse
import time
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from langchain_core.messages import HumanMessage

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from agent_runner import run_chat_turn  # noqa: E402

CITY_GPS = {
    "San Francisco": (37.7955, -122.3937),
    "Kolkata": (22.5726, 88.3639),
}


def load_queries(path: Path) -> tuple[dict, list[dict]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw.get("meta", {}), raw.get("queries", [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-prefix", default="")
    parser.add_argument("--start", type=int, default=1, help="1-based start index (inclusive)")
    parser.add_argument("--end", type=int, default=0, help="1-based end index (inclusive), 0 means all")
    parser.add_argument("--append", action="store_true", help="Append to existing output files")
    parser.add_argument("--delay-sec", type=float, default=0.0, help="Sleep between queries")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per query on transient failures")
    parser.add_argument("--skip-existing", action="store_true", help="Skip indices already present in output jsonl")
    args = parser.parse_args()

    meta, queries = load_queries(ROOT / "evaluation" / "queries.yaml")
    out_dir = ROOT / "evaluation" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    prefix = args.out_prefix.strip() or f"small_answers_{ts}"
    md_file = out_dir / f"{prefix}.md"
    jsonl_file = out_dir / f"{prefix}.jsonl"

    total = len(queries)
    start_idx = max(1, args.start)
    end_idx = args.end if args.end and args.end > 0 else total
    end_idx = min(total, end_idx)
    if start_idx > end_idx:
        print("Invalid range: start is greater than end")
        return 1

    selected_queries = queries[start_idx - 1 : end_idx]

    done_indices: set[int] = set()
    if args.skip_existing and jsonl_file.exists():
        for line in jsonl_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                idx_val = row.get("index")
                if isinstance(idx_val, int):
                    done_indices.add(idx_val)
            except Exception:
                continue

    lines: list[str] = []
    if not args.append or not md_file.exists():
        lines.append("# Small Model Answers\n")
        lines.append(f"Generated: {ts} UTC\n")
        lines.append(f"Total queries: {total}\n")
        lines.append(f"Executed range this run: {start_idx}-{end_idx}\n")
    else:
        lines.append(f"\n## Batch {start_idx}-{end_idx}\n")

    for local_idx, q in enumerate(selected_queries, start=0):
        idx = start_idx + local_idx
        if idx in done_indices:
            print(json.dumps({"index": idx, "skipped": True}), flush=True)
            continue

        uid = meta.get("user_id", "student_1")
        city = q.get("city") or meta.get("default_city", "San Francisco")
        lat = q.get("latitude")
        lng = q.get("longitude")
        if lat is None or lng is None:
            lat, lng = CITY_GPS.get(city, (37.7955, -122.3937))

        qid = q.get("id", f"q{idx:02d}")
        text = q.get("text", "")

        human = HumanMessage(
            content=(
                f"Backend context: user_id={uid}; GPS=Lat: {lat}, Long: {lng}; focus_city={city}.\n\n"
                f"{text}"
            )
        )

        answer, elapsed = "", -1.0
        error = None
        for attempt in range(1, max(1, args.max_retries) + 1):
            try:
                answer, elapsed = run_chat_turn(
                    [human],
                    tier="small",
                    user_id=uid,
                    city=city,
                    latitude=lat,
                    longitude=lng,
                )
                error = None
                break
            except BaseException as exc:
                error = repr(exc)
                # Respect OpenRouter reset header when present.
                m = re.search(r"X-RateLimit-Reset': '([0-9]+)'", error)
                if m and attempt < max(1, args.max_retries):
                    try:
                        reset_epoch_ms = int(m.group(1))
                        wait_sec = max(1.0, (reset_epoch_ms / 1000.0) - time.time() + 1.0)
                    except Exception:
                        wait_sec = 15.0
                    print(json.dumps({"index": idx, "retry": attempt, "wait_sec": round(wait_sec, 2), "reason": "rate_limit"}), flush=True)
                    time.sleep(wait_sec)
                    continue
                if attempt < max(1, args.max_retries):
                    backoff = min(30.0, 2.0 * attempt)
                    print(json.dumps({"index": idx, "retry": attempt, "wait_sec": backoff, "reason": "transient_error"}), flush=True)
                    time.sleep(backoff)
                    continue
                answer, elapsed = "", -1.0
                break

        answer = (answer or "").strip()
        row = {
            "index": idx,
            "query_id": qid,
            "city": city,
            "tier": "small",
            "elapsed_sec": elapsed,
            "query": text,
            "answer": answer,
            "error": error,
        }
        with open(jsonl_file, "a", encoding="utf-8") as jf:
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")

        lines.append(f"## {idx}. {qid} ({city})\n")
        lines.append(f"**Query**: {text}\n")
        lines.append(f"**Elapsed**: {elapsed:.2f}s\n")
        if error:
            lines.append(f"**Error**: {error}\n")
            lines.append("**Answer**: _No answer due to error._\n")
        else:
            lines.append("**Answer**:\n")
            lines.append(answer if answer else "_Empty response._")
            lines.append("\n")

        print(json.dumps({"index": idx, "query_id": qid, "elapsed_sec": elapsed, "error": bool(error)}), flush=True)
        if args.delay_sec > 0:
            time.sleep(args.delay_sec)

    with open(md_file, "a", encoding="utf-8") as mf:
        mf.write("\n".join(lines) + "\n")
    print(f"Wrote markdown: {md_file}")
    print(f"Wrote jsonl: {jsonl_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
