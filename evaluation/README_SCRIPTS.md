# Evaluation & QA Scripts Guide

## Overview

The `evaluation/` directory contains scripts for testing, validation, and analysis. Below is a guide to each script.

---

## 📊 Primary Evaluation Script

### `run_eval.py` - Main Test Harness

**Purpose**: Run comprehensive evaluation against 40 queries (20 cities × 2 tiers)

**Usage**:
```bash
cd backend && source venv/bin/activate
export OPENROUTER_API_KEY=sk-or-v1-...
python ../evaluation/run_eval.py [OPTIONS]
```

**Options**:
```
--queries FILE        Path to query file (default: evaluation/queries.yaml)
--tier {small|large|both}  Which tiers to test (default: both)
--injection           Run security injection tests instead of queries
```

**Examples**:
```bash
# Run both tiers against all 40 queries
python ../evaluation/run_eval.py

# Run only small tier
python ../evaluation/run_eval.py --tier small

# Run security injection tests
python ../evaluation/run_eval.py --injection

# Use custom query file
python ../evaluation/run_eval.py --queries custom_queries.yaml
```

**Output**: 
- Creates `results/eval_TIMESTAMP.jsonl` with results
- Each line: `{"query_id": "san01", "tier": "small", "elapsed_sec": 18.5, "answer_preview": "..."}`

**Prerequisites**:
- Backend running on port 8000 OR use OpenRouter API
- `backend/requirements.txt` installed
- Valid `OPENROUTER_API_KEY` in `.env`

---

## 📈 Analysis Scripts

### `analyze_results.py` - Result Analysis

**Purpose**: Aggregate and summarize evaluation results

**Usage**:
```bash
python analyze_results.py
```

**Output**:
```
Found 4 result files
  Loading: eval_*.jsonl
  ...

WALKIE-TALKIE MODEL COMPARISON REPORT
================================================================================

OVERALL METRICS BY TIER
  SMALL TIER:
    Query Count: 36
    Mean Latency: 47.55s
    Median (p50): 38.93s
    p90: 78.75s
  ...
```

**Automatically**:
- Loads all JSONL files from `results/`
- Groups by tier and city
- Calculates statistics (mean, median, p90)
- Compares small vs large performance

---

### `summarize_eval.py` - JSON Summary Generation

**Purpose**: Create machine-readable summary of evaluation results

**Usage**:
```bash
python summarize_eval.py \
  --input results/eval_20260514T020847Z.jsonl \
  --out results/summary.json
```

**Output**: 
```json
{
  "small": {
    "count": 40,
    "mean": 18.81,
    "p50": 18.0,
    "p90": 21.0,
    "error_rate": 0.0
  },
  "large": {
    "count": 40,
    "mean": 20.15,
    "p50": 19.0,
    "p90": 23.0,
    "error_rate": 0.0
  }
}
```

---

### `slice_queries.py` - Split Queries into Smoke/Full Tests

**Purpose**: Create smoke test (quick subset) and full test suites

**Usage**:
```bash
python slice_queries.py \
  --input queries.yaml \
  --out-smoke queries_smoke.yaml \
  --out-rest queries_remaining.yaml
```

**Example Output**:
```
Smoke queries: 14 (fast baseline)
Remaining queries: 26 (comprehensive)
```

**Smoke Test IDs** (default):
```
san01, san02, san06, san07, san11, san16, san18 (SF)
kol01, kol02, kol06, kol07, kol11, kol16, kol18 (Kolkata)
```

---

## 🧪 Interactive QA Scripts

### `auth_isolation_qa.py` - Multi-User Session Testing

**Purpose**: Test user isolation, profile persistence, and session management

**Prerequisites**:
- Backend running on `http://127.0.0.1:8001`
  ```bash
  uvicorn main:app --port 8001
  ```

**Usage**:
```bash
cd backend
python auth_isolation_qa.py
```

**Tests**:
1. ✅ User sign-in with casing/whitespace normalization
2. ✅ Profile updates (budget, dietary preferences)
3. ✅ Visited place recording per user
4. ✅ Session identity resolution
5. ✅ Token revocation and logout
6. ✅ Cross-user isolation

**Expected Output**:
```json
{
  "signin_alice": {"ok": true, "user_id": "alice"},
  "signin_bob": {"ok": true, "user_id": "bob"},
  "profile_alice": {...},
  "visited_alice": {...},
  "me_alice": {...},
  "logout_alice": {...},
  "me_alice_after_logout": {"ok": false, "error": "Invalid token"},
  "me_bob_after_alice_logout": {...}
}
```

---

### `comprehensive_qa.py` - Interactive Model Query Testing

**Purpose**: Test specific queries against both model tiers with detailed output

**Usage**:
```bash
cd backend
python comprehensive_qa.py
```

**Tests** (hardcoded query IDs):
```python
["san01", "san10", "san11", "san18", "san08"]  # SF queries
```

**Output**:
```
============================================================
### MODEL TIER: SMALL
============================================================

--- [QUERY san01] ---
QUESTION: What are 5 cheap lunch spots near a historic district...
CITY: San Francisco

STEPS:
  1. Context Building: Retrieving user profile and local history...
  2. System Prompt: Applying Local Friend Persona...
  3. Inference: Processing through OpenRouter API...
  4. Tool Use: Monitoring for search_web or get_weather...
  5. Reflection: Self-correcting for factual humility.
  6. Done! Elapsed Time: 18.50s

[USER OUTPUT]:
vvvvvvvvvvvvvvvvvvvvvvvvvvvvvvv
[Response text here]
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

**To Modify**:
Edit `TEST_QUERY_IDS` in the script to test different queries.

---

## 🔍 Test Suite Files

### `queries.yaml` - Master Evaluation Query Set

**Structure**:
```yaml
meta:
  user_id: student_1
  default_city: San Francisco

queries:
  - id: san01
    text: "What are 5 cheap lunch spots..."
    city: San Francisco
  - id: kol01
    text: "What are 5 cheap lunch spots..."
    city: Kolkata
  # 40 total queries (20 per city)
```

**Coverage**:
- Budget planning (san02, kol02)
- Cultural knowledge (san06, kol06)
- Walking routes (san07, kol07)
- Transit info (san11, kol11)
- Image recognition (san16, kol16)
- Weather integration (san18, kol18)
- And 28 more...

---

## 📂 Result Files

### Location
```
evaluation/results/
├── eval_20260514T014612Z.jsonl    (40 small tier queries)
├── eval_20260508T201101Z.jsonl    (11 injection tests)
├── eval_20260508T194753Z.jsonl    (11 injection tests)
└── eval_20260514T020847Z.jsonl    (80 rows, mixed tiers)
```

### Format
Each line is a JSON object:
```json
{
  "query_id": "san01",
  "tier": "small",
  "elapsed_sec": 18.81,
  "answer_preview": "Here are 2 budget-friendly lunch spots..."
}
```

---

## 🚀 Common Workflows

### Workflow 1: Quick Smoke Test
```bash
# Generate smoke queries
python slice_queries.py \
  --input queries.yaml \
  --out-smoke queries_smoke.yaml \
  --out-rest queries_rest.yaml

# Run smoke test
cd backend && source venv/bin/activate
python ../evaluation/run_eval.py --tier both --queries ../evaluation/queries_smoke.yaml
```

### Workflow 2: Full Evaluation with Analysis
```bash
# Run full eval (both tiers, 40 queries)
cd backend && source venv/bin/activate
python ../evaluation/run_eval.py --tier both

# Analyze results
cd ../evaluation
python analyze_results.py
```

### Workflow 3: Injection Security Testing
```bash
# Run injection tests (prompt injection, API key leakage, etc.)
cd backend && source venv/bin/activate
python ../evaluation/run_eval.py --injection

# Analyze security results
cd ../evaluation
python analyze_results.py
```

### Workflow 4: Manual QA Before Release
```bash
# Terminal 1: Start backend on port 8001
cd backend && source venv/bin/activate
uvicorn main:app --port 8001

# Terminal 2: Run multi-user session tests
cd backend
python auth_isolation_qa.py

# Terminal 3: Run interactive query tests
cd backend
python comprehensive_qa.py
```

---

## ⚙️ Configuration

### Backend Requirements
Ensure `.env` has:
```env
OPENROUTER_API_KEY=sk-or-v1-...
SMALL_LLM_MODEL=nvidia/nemotron-nano-9b-v2:free
LARGE_LLM_MODEL=nvidia/nemotron-3-nano-30b-a3b:free
FORCE_OLLAMA_FALLBACK=false  # Use OpenRouter
```

### Model Tiers
- **Small**: `nvidia/nemotron-nano-9b-v2:free` (9B params, faster, cheaper)
- **Large**: `nvidia/nemotron-3-nano-30b-a3b:free` (30B params, better reasoning)

---

## 📊 Expected Performance

### Latency (p50 / p90)
- **Small**: ~18s / ~21s per query
- **Large**: ~20s / ~23s per query

### Error Rate
- Expected: 0% (both tiers should have no failures)
- If > 0%: Check API key, rate limits, network

### Quality Metrics
See `evaluation/FINAL_MODEL_COMPARISON.md` for detailed comparison

---

## 🐛 Troubleshooting

### Error: "Connection refused: 8000"
**Solution**: Start backend
```bash
cd backend && source venv/bin/activate
uvicorn main:app --reload --port 8000
```

### Error: "Rate limit exceeded"
**Solution**: OpenRouter free tier has daily limits
- Smoke test instead: `python slice_queries.py` then test only 14 queries
- OR upgrade OpenRouter plan

### Error: "Prompt missing required variables: 'agent_scratchpad'"
**Solution**: This is a LangChain version issue
- Already fixed in latest `agent_runner.py`
- Restart backend to reload

---

## 📝 Scripts Reference

| Script | Purpose | Runs Queries | Useful For |
|--------|---------|--------------|-----------|
| `run_eval.py` | Main evaluator | 40 (or custom) | Full evaluation |
| `analyze_results.py` | Result analysis | N/A | Post-eval analysis |
| `summarize_eval.py` | JSON summary | N/A | Metrics export |
| `slice_queries.py` | Split queries | N/A | Quick testing |
| `auth_isolation_qa.py` | Auth testing | N/A | Multi-user validation |
| `comprehensive_qa.py` | Manual testing | 5 (hardcoded) | Interactive debugging |
| `generate_queries.py` | Generate query set | N/A | Create new test suite |

---

