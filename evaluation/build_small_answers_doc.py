from __future__ import annotations

import json
from pathlib import Path

import yaml

root = Path(__file__).resolve().parent.parent
queries_path = root / "evaluation" / "queries.yaml"
results_path = root / "evaluation" / "results" / "eval_20260425T230130Z.jsonl"
out_path = root / "evaluation" / "results" / "small_model_answers_20260425.md"

qraw = yaml.safe_load(queries_path.read_text(encoding="utf-8"))
queries = qraw.get("queries", [])

rows: dict[str, dict] = {}
for line in results_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line:
        continue
    row = json.loads(line)
    qid = row.get("query_id")
    if qid:
        rows[qid] = row

lines: list[str] = [
    "# Small Model Query Answers",
    "",
    "Source run: eval_20260425T230130Z.jsonl",
    "",
]

for i, q in enumerate(queries, start=1):
    qid = q.get("id", f"q{i:02d}")
    city = q.get("city", "")
    text = q.get("text", "")
    row = rows.get(qid, {})
    elapsed = row.get("elapsed_sec", "n/a")
    answer = row.get("answer_preview", "(no result)")

    lines.extend(
        [
            f"## {i}. {qid} ({city})",
            f"**Query**: {text}",
            f"**Elapsed (s)**: {elapsed}",
            "**Answer**:",
            answer,
            "",
        ]
    )

out_path.write_text("\n".join(lines), encoding="utf-8")
print(out_path)
