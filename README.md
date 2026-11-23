# Agent Monitoring System

Runs a task through an agent, records exactly what the agent did, aggregates that
into evidence, has a reviewer evaluate it, and shows the result (trace, review,
trust score) in a dashboard.

This is a **starter**: the plumbing, contracts and tests are real; the agent is a
mock and the reviewer is deliberately narrow. See "What is real and what is mock".

```
Task ─► Agent ─► Trace ─► Evidence ─► Reviewer ─► Audit ─► Trust ─► Improvements
        (mock)   (real)   (real)      (real,      (real)   (placeholder)
                                       rule-based)
                  └──────── Person 1 ────────┘└────────────── Person 2 ──────────┘
                              stored in SQLite, served by FastAPI, shown by React
```

## Quick start

Needs Python 3.10+ and Node 18+. From the project root:

```bash
# 1. Backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                 # optional; defaults work
uvicorn backend.app.main:app --reload --port 8000

# 2. Frontend (second terminal)
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

The frontend works **without** the backend too: it falls back to the bundled sample
data and says so in the banner at the top.

```bash
# Tests (from the project root, venv active)
pytest
```

More detail: [docs/setup_guide.md](docs/setup_guide.md).

## Who owns what

| Area | Owner | Files |
|---|---|---|
| Backend, agent, trace, evidence, database, integration | Person 1 | `backend/` |
| Reviewer, audit, trust calibration, improvement | Person 2 | `reviewer/` |
| Frontend and dashboard | Person 2 | `frontend/` |
| Contracts and sample data | Both | `shared/`, `docs/api_contract.md` |

Working in parallel needs only the shared files:

- **Person 2** builds against `shared/sample_data/sample_execution.json` and
  `sample_evidence.json`. `reviewer/` imports nothing from `backend/`. The frontend runs
  on bundled samples with no backend.
- **Person 1** treats the reviewer as one call, `reviewer.review_execution(execution, evidence)`,
  and the frontend as a consumer of `docs/api_contract.md`.
- Changing a shared schema: edit `shared/schemas/*.json` **and**
  `backend/app/api/schemas.py` in the same pull request. `tests/test_integration.py`
  fails if they drift apart.

## What is real and what is mock

| Component | Status | What it actually does |
|---|---|---|
| Agent executor (`backend/app/agent/executor.py`) | **MOCK** | Deterministic rule-based "agent". No LLM. |
| Tools: calculator, text_stats | Real | Genuinely compute results. |
| Fault injection | Test-only | Deliberately corrupts a run so the reviewer has something to catch. |
| Trace recorder | Real | Records every step with timing and errors. |
| Evidence aggregation | Real | Counts, errors, timing, tool outputs a reviewer can re-check. |
| Reviewer evaluation | Real, narrow | Six mechanical checks, including re-computing tool outputs independently. Does **not** judge answer quality or reasoning. |
| Reviewer audit | Real | Checks the review's own bookkeeping (score reproducible, cited steps exist, no check dropped). |
| Reviewer validation | Real | Validates output against `shared/schemas/reviewer.json`. |
| Trust calibration | **Placeholder** | Real maths (Beta posterior over weighted check results) but **not calibrated** against ground truth. Marked `beta_prior_uncalibrated`. |
| Controlled improvement | **Placeholder** | Fixed lookup from failed check to suggested fix. Proposals only; nothing is applied automatically. |
| Database, API, frontend | Real | SQLite via SQLAlchemy, FastAPI, React + Vite. |

Every module's docstring starts with its `STATUS`.

## Try it

Submit a task in the UI, or:

```bash
curl -X POST localhost:8000/api/tasks -H 'content-type: application/json' \
  -d '{"task": "What is (12 + 8) * 3 / 4?"}'
# add "fault_injection": "wrong_tool_result" and watch the reviewer catch it
curl localhost:8000/api/executions
```

Supported tasks: arithmetic (`What is 6 * 7?`) and word counts
(`Count the words in: the quick brown fox`).

## Regenerating sample data

`shared/sample_data/` is real pipeline output, not hand-written. After changing the
agent, evidence or reviewer: `python scripts/generate_samples.py`.

## Layout

```
backend/      FastAPI app (Person 1)         reviewer/   reviewer modules (Person 2)
frontend/     React + Vite (Person 2)        shared/     JSON schemas + sample data
tests/        pytest                         scripts/    sample-data generator
data/         runtime JSON + SQLite file     docs/       architecture, API contract, setup
```
