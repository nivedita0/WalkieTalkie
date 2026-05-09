# WalkieTalkie SDE Review and Cleanup Report

## Scope
- Reviewed backend, frontend, and evaluation assets for maintainability, risk, and cleanup opportunities.
- Focused cleanup on low-risk, non-functional artifacts to keep report evidence while reducing noise.

## High-Priority Findings
- Backend currently filters out `system` role messages, while frontend sends multiple system prompts. This mismatch can make prompt design appear ineffective and should be aligned.
- Chat request handling has edge-case risk if malformed payloads produce empty `messages` arrays before final message access.
- CORS policy is very permissive for production use and should be restricted by environment.

## Improvement Opportunities
- Split `walkie-talkie-app/src/App.jsx` into smaller feature modules (auth/session, chat orchestration, itinerary, walking mode) to reduce regression risk.
- Add API-level contract tests for `/api/chat`, `/api/auth/*`, and itinerary generation to catch payload and fallback regressions.
- Standardize one evaluation entrypoint and reduce one-off scripts to simplify reproducibility.
- Keep one canonical model/config matrix in docs to avoid drift between code and evaluation notes.

## Redundant or Potentially Redundant Areas
- Duplicate-like weather/testing scripts under `backend/` can be consolidated into one maintained smoke test.
- Overlapping evaluation helpers should be reduced to one canonical pipeline to limit drift and stale outputs.
- Large generated/runtime artifacts should not be tracked; rely on reproducible commands instead.

## Cleanup Performed
- Updated `.gitignore` to ignore:
  - Python cache and virtualenv folders
  - Node dependency folders
  - Local DB and vector-store runtime artifacts
  - OS clutter files
- Removed files that are not needed for long-term source history:
  - `.DS_Store`
  - `WalkieTalkie  (1).txt`
  - `evaluation/results/small_model_answers_20260425.md` (redundant compared with retained result artifacts)

## Kept for Report Reproducibility
- `evaluation/REPORT.md`
- `evaluation/EXECUTION_CHECKLIST.md`
- `evaluation/queries.yaml`
- `evaluation/results/small_answers_20260425T230221Z.jsonl`
- `evaluation/results/small_answers_20260425T230221Z.md`
- `evaluation/results/sf_prompt_modes_raw_20260426.json`
- `evaluation/results/sf_prompt_modes_comparison_20260426.md`
- `evaluation/results/test_results_20260424.md`

## Suggested Next Engineering Actions
1. Align frontend prompt strategy with backend message handling (either preserve system messages or move all control to backend).
2. Add strict request validation and guard conditions in chat endpoint.
3. Break down frontend monolith and add targeted tests around critical flows.
4. Rebuild vector DB with embedding dimensions that match current embedding model.
