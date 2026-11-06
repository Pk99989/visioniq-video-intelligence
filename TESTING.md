# TESTING

## How to run (2026-11-06, v0.12.0+)

Backend (from `backend/`, venv active):

```bash
# Full suite (unit + integration markers that can run here; e2e and
# vlm are excluded — see markers below):
SYNC_PROCESSING=1 python -m pytest tests/ -q
# Fast unit tests only (SQLite, mocks allowed):
python -m pytest tests/ -q -m unit
# Live-infra tests (need Postgres/Redis/Qdrant running):
python -m pytest tests/ -q -m integration
# Real-VLM tests (need Ollama + moondream + Qdrant):
VISIONIQ_VLM_E2E=1 python -m pytest tests/ -q -m vlm
# Browser end-to-end (needs the live backend + frontend):
VISIONIQ_E2E=1 python -m pytest tests/test_e2e_browser.py -q
# With coverage (gate: 70% on app/services):
pip install -r requirements-dev.txt
python -m pytest tests/ -q -m "not integration and not e2e and not vlm" \
  --cov=app.services --cov-report=term-missing --cov-fail-under=70
```

Frontend (from `frontend/`): `npm test` (Vitest) and `npm run build`.

CI (`.github/workflows/ci.yml`): the `backend` job runs the unit
markers with the coverage gate; `backend-integration` runs the
integration markers against Postgres 16 / Redis 7 / Qdrant v1.20.0
service containers; `frontend` runs the build.

## Markers (Phase 11)

| Marker | Meaning | Runs where |
|---|---|---|
| `unit` | Fast, SQLite, mocks allowed. Auto-applied by `conftest.py` to any test with no other marker. | Every run, CI unit job |
| `integration` | Needs live Postgres / Redis / Qdrant; skips when unreachable. | CI integration job, local servers |
| `vlm` | Needs a real Ollama model server (`VISIONIQ_VLM_E2E=1`). | Explicit runs only |
| `e2e` | Browser workflow (`VISIONIQ_E2E=1`). | Explicit runs only |

Current counts (2026-11-06): 105 unit, 3 integration, 2 vlm,
1 e2e — 111 backend tests total.

## Shared fixtures (`backend/tests/conftest.py`, Phase 11)

- `client` — TestClient for the app (imported lazily; the test
  module's own DATABASE_URL setdefaults win).
- `auth_user` — a fresh user (uuid email, no cross-file collisions);
  returns `{"email", "headers", "user_id"}` with the id resolved
  from the DB, never hardcoded (audit L12).
- `ready_video` — the bus video uploaded for `auth_user`, ready.
- `bus_video` — a 3 s bus video built per-test in `tmp_path`.
- `bus_jpg` / `traffic_jpg` / `fixtures_dir` — repo-local test
  images in `backend/tests/data/` (they used to live in `/tmp` and
  were wiped by VM restarts; they are committed now).
- `db_session` — a SessionLocal on the live engine.
- `_rate_limit_off` (session, autouse) — the auth rate limiter is
  off for the suite; the dedicated rate-limit tests re-enable it.

L12 rules (learned the hard way): the first test module to import
the app freezes the settings singleton and the shared engine's
DATABASE_URL, so (a) `conftest.py` sets `SYNC_PROCESSING=1` before
any test module loads, (b) every file deletes its own DB/storage at
import (a file that does not — test_detection.py used not to — leaks
state across runs), and (c) subprocess tests (e.g. make_admin) take
the engine's URL, not the process env's.

## Suites by phase

- `test_api.py` — full flow (upload → ready → search/chat/summary/
  events/report), upload validation.
- `test_security.py` — 22 tests: H1 reset-token rules, JWT attacks,
  refresh rotation/replay, cross-user 404 on every video route,
  rate-limit 429, magic bytes, 413, traversal, scan hook, SSRF,
  make_admin.
- `test_detection.py` — Tracker lifecycle, calibration, trajectories,
  real-model checks on bus.jpg / traffic frame (skipped without
  weights).
- `test_retrieval.py` — Qdrant-first search, DB fallback, filters,
  reranker, dedupe, citation validation.
- `test_rag_eval.py` — the 54-question eval as a regression test
  (vlm): R@5 ≥ 0.60, MRR ≥ 0.40, faithfulness ≥ 0.90,
  relevance ≥ 0.85, negatives ≥ 0.30 (baseline 2026-11-06:
  R@5 0.66, MRR 0.48, faithfulness 1.0, relevance 0.95,
  negatives 0.38 — see `docs/benchmarks/rag-eval-2026-11-06.md`).
  The full 4-config comparison stays in `scripts/rag_eval.py`.
- `test_agent.py` / `test_mcp.py` — 8-tool registry, deterministic
  planning, owner scoping, stdio + HTTP MCP.
- `test_events.py` — zone state machine, dwell/loitering, evidence
  clips, VLM verification.
- `test_postgres.py` / `test_celery_reliability.py` — migrations,
  pooling, recovery grace, task limits, failure handler.
- `test_observability.py` — /metrics counters after upload+search,
  request-ID echo, JSON formatter, METRICS_ENABLED=0.
- `test_vlm.py` (mock servers) / `test_vlm_e2e.py` (real model,
  vlm) — caption tiers, retries, structured JSON.
- `test_e2e_browser.py` — Playwright: register → upload → ready →
  search + filters → clip download → chat + follow-up → reopen →
  dashboard stats → 360 px check → sign out.
- Frontend Vitest: `lib/api.test.ts` + `components/ui.test.tsx`
  (10 tests).

## Coverage (Phase 11)

Measured 2026-11-06: **80% on `app/services`** (gate: 70%).
Weakest file is `embeddings.py` (44% — the fastembed /
sentence-transformers paths need model downloads / torch and are
not covered by the unit suite). Coverage is reported, not gamed:
a threshold that fails is fixed by adding tests, not by excluding
code.

## Benchmarks — method (still applies)

The master prompt lists Recall@K, Precision@K, RAG faithfulness,
detection precision/recall, tracking quality, summary consistency,
alert false-positive rate, latency and memory. Measured values live
in `docs/benchmarks/` and PROJECT_STATE.md; nothing else in this
repo is a measured number. Method for new measurements:

1. Build a small labelled set: 5–10 short videos, each with 5 known
   moments (query → expected timestamp ±2 s) and 3 known objects.
2. Search: Recall@5/Precision@5 = fraction of expected moments in
   the top 5 / fraction of top 5 that are correct.
3. RAG: faithfulness = fraction of answer claims traceable to a cited
   timestamp; report the no-evidence rate separately.
4. Detection: precision/recall against hand-labelled boxes at IoU ≥ 0.5.
5. Summaries: factual consistency = claims in the summary that appear
   in a scene caption, checked manually for the first release.
6. Alerts: false-positive rate = alerts fired / alerts evaluated on
   videos known to contain no event, per rule.
7. Report latency (p50/p95 per endpoint) and peak RSS during a
   10-minute video ingest, on the RTX 3050 laptop.

## Historical results

- v0.1.0 (2026-11-04): 2 backend tests passed (full flow + upload
  validation), frontend build passed.
- v0.2.0–v0.3.1 (2026-11-05/06): 10 backend tests; live Postgres /
  Qdrant / Redis + Celery verified; Playwright e2e passed.
- v0.4.0–v0.10.0: 28 → 84 backend tests (Phases 0–8), + 10 Vitest
  + 1 e2e + 1 real-VLM e2e.
- v0.11.0 (Phase 9): 102 backend tests.
- v0.12.0 (Phase 10): 108 backend tests.
