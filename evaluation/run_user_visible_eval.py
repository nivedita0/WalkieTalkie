#!/usr/bin/env python3
"""
User-visible latency: time until the streamed /api/chat response is complete (same path as the React app).

Measures wall-clock from POST start until the HTTP stream ends — when the full assistant text is available
to render in the UI. Includes agent, tools, reflection (if prompting_mode=self_reflection), and streaming.

Usage (repo root, backend already on :8000):
  python evaluation/run_user_visible_eval.py
  python evaluation/run_user_visible_eval.py --limit 14 --tier both
  python evaluation/run_user_visible_eval.py --modes regular,meta,chaining,self_reflection --limit 1

Outputs:
  evaluation/results/user_visible_eval_<UTC_ts>.jsonl
  evaluation/results/user_visible_eval_<UTC_ts>_summary.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "evaluation" / "results"

CITY_GPS = {
    "San Francisco": (37.7955, -122.3937),
    "Kolkata": (22.5726, 88.3639),
}


def load_queries(path: Path) -> tuple[dict, list[dict]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw.get("meta", {}), raw.get("queries", [])


def stream_chat(
    base_url: str,
    text: str,
    city: str,
    lat: float,
    lng: float,
    llm_tier: str,
    prompting_mode: str,
    timeout_sec: int,
) -> tuple[str, float, int | None]:
    """
    Returns (full_reply, elapsed_sec, http_status).
    """
    url = base_url.rstrip("/") + "/api/chat"
    body = {
        "llm_tier": llm_tier,
        "city": city,
        "stream": True,
        "prompting_mode": prompting_mode,
        "messages": [{"role": "user", "content": text}],
        "latitude": lat,
        "longitude": lng,
        "session_token": None,
    }
    t0 = time.perf_counter()
    full = []
    status = None
    with requests.post(url, json=body, stream=True, timeout=timeout_sec) as r:
        status = r.status_code
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                obj = json.loads(line)
                chunk = obj.get("message", {}).get("content", "")
                if chunk:
                    full.append(chunk)
            except json.JSONDecodeError:
                continue
    elapsed = time.perf_counter() - t0
    return "".join(full).strip(), elapsed, status


def main() -> int:
    parser = argparse.ArgumentParser(description="User-visible /api/chat stream latency eval")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Backend base URL (no trailing path)")
    parser.add_argument("--queries", default=str(ROOT / "evaluation" / "queries.yaml"))
    parser.add_argument("--tier", choices=("small", "large", "both"), default="both")
    parser.add_argument(
        "--modes",
        default="self_reflection",
        help="Comma-separated prompting_mode values (e.g. regular,meta,chaining,self_reflection)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Max queries to run (0 = all)")
    parser.add_argument("--timeout", type=int, default=900, help="Per-request timeout seconds")
    parser.add_argument("--prefix", default="", help="Optional id prefix filter, e.g. san for SF only")
    args = parser.parse_args()

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    tiers = ["small", "large"] if args.tier == "both" else [args.tier]

    health = requests.get(args.url.rstrip("/") + "/api/health", timeout=10)
    if health.status_code != 200:
        print(f"ERROR: GET /api/health -> {health.status_code}", file=sys.stderr)
        return 1

    meta, queries = load_queries(Path(args.queries))
    uid = meta.get("user_id", "student_1")

    if args.prefix:
        queries = [q for q in queries if str(q.get("id", "")).startswith(args.prefix)]
    if args.limit and args.limit > 0:
        queries = queries[: args.limit]

    if not queries:
        print("No queries to run.", file=sys.stderr)
        return 1

    RESULTS.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_jsonl = RESULTS / f"user_visible_eval_{ts}.jsonl"
    rows_for_summary: list[dict] = []

    print(f"Writing {out_jsonl}")
    print(f"Queries: {len(queries)} x tiers={tiers} x modes={modes} (user_id={uid})")

    with open(out_jsonl, "w", encoding="utf-8") as out_f:
        for q in queries:
            qid = q.get("id")
            city = q.get("city") or meta.get("default_city", "San Francisco")
            text = q["text"]
            lat = q.get("latitude")
            lng = q.get("longitude")
            if lat is None or lng is None:
                lat, lng = CITY_GPS.get(city, (37.7955, -122.3937))

            for tier in tiers:
                for mode in modes:
                    print(f"  {qid} | {tier} | {mode} ...", flush=True)
                    try:
                        answer, elapsed, status = stream_chat(
                            args.url,
                            text,
                            city,
                            float(lat),
                            float(lng),
                            tier,
                            mode,
                            args.timeout,
                        )
                        err = None
                    except Exception as e:
                        answer, elapsed, status = "", -1.0, None
                        err = repr(e)

                    row = {
                        "query_id": qid,
                        "city": city,
                        "tier": tier,
                        "prompting_mode": mode,
                        "elapsed_sec_user_visible": round(elapsed, 3) if elapsed >= 0 else elapsed,
                        "http_status": status,
                        "answer": answer,
                        "answer_char_len": len(answer),
                        "error": err,
                    }
                    out_f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out_f.flush()
                    rows_for_summary.append(row)

    # Summary aggregates (successful runs only)
    def stats_for(key: str, val: str, rows: list[dict]) -> dict:
        subset = [r["elapsed_sec_user_visible"] for r in rows if r.get(key) == val and r.get("error") is None and r["elapsed_sec_user_visible"] >= 0]
        if not subset:
            return {"count": 0}
        return {
            "count": len(subset),
            "mean_sec": round(statistics.mean(subset), 3),
            "median_sec": round(statistics.median(subset), 3),
            "min_sec": round(min(subset), 3),
            "max_sec": round(max(subset), 3),
        }

    summary = {
        "generated_at_utc": ts,
        "method": "Wall time for complete streamed POST /api/chat until stream closes (user-visible answer).",
        "url": args.url,
        "by_tier": {t: stats_for("tier", t, rows_for_summary) for t in tiers},
        "by_mode": {m: stats_for("prompting_mode", m, rows_for_summary) for m in modes},
    }
    summary_path = RESULTS / f"user_visible_eval_{ts}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
