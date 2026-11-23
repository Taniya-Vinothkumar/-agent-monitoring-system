# Architecture

## Pipeline

`backend/app/services/integration.py` is the only module that knows the whole flow:

```
POST /api/tasks
   │
   ▼
MockAgentExecutor.run(TaskRequest)          agent/executor.py       Person 1  (MOCK)
   │   records every step via
   ▼
TraceRecorder  ──►  ExecutionTrace          monitoring/trace_recorder.py
   │
   ▼
aggregate_evidence(trace) ──► EvidenceSummary   monitoring/evidence.py
   │
   ▼   (Pydantic models → plain dicts)
reviewer.review_execution(execution, evidence)  reviewer/__init__.py   Person 2
   ├─ evaluator.evaluate         six rule-based checks, score, verdict
   ├─ audit.audit_review         audits the review itself
   ├─ trust_calibration.calibrate_trust
   ├─ improvement.propose_improvements
   └─ validation.validate_review  output checked against shared/schemas/reviewer.json
   │
   ▼   (dict → ReviewerResult, validated again by Pydantic)
SQLite (executions, reviews)   +   data/executions/*.json, data/evaluation/*.json
```

## The boundary between the two people

One function, with data shapes fixed by the JSON schemas:

```python
reviewer.review_execution(execution: dict, evidence: dict) -> dict
#   execution  conforms to shared/schemas/execution.json
#   evidence   conforms to shared/schemas/evidence.json
#   returns    conforms to shared/schemas/reviewer.json
```

`reviewer/` does not import `backend/`. The reviewer deliberately re-implements the
arithmetic check instead of importing the agent's calculator, so it does not inherit
the agent's bugs.

## Reviewer checks

| Check | Severity | Passes when |
|---|---|---|
| `final_answer_present` | critical | the run produced a final answer |
| `no_step_errors` | critical | no step errored |
| `trace_step_ids_consecutive` | warning | step ids are 1..n in order |
| `tool_results_independently_verified` | critical | each tool output equals the reviewer's own re-computation (skipped if none) |
| `final_answer_matches_tool_results` | critical | the answer states the tool's value (skipped if none) |
| `latency_within_budget` | warning | total time ≤ `LATENCY_BUDGET_MS` |

Score = severity-weighted share of non-skipped checks that passed (info 1, warning 2,
critical 3). Verdict: any failed critical → `fail`; any other failure →
`needs_attention`; else `pass`.

**Known limits:** the answer check looks for a number in the answer text; it cannot
judge wording or reasoning. Calculator claims are limited to `+ - * / %`.

## Trust

`trust.score` is the mean of Beta(1 + passed weight, 1 + failed weight), with a 95%
normal-approximation range. It is capped at 0.5 when a critical check failed or the
review failed its audit. It is **not calibrated**: that needs labelled ground truth
this project does not have yet. Replacing it means changing only
`reviewer/trust_calibration.py`; the output shape stays.

## Controlled improvement

Proposals only (`status: "proposed"`, `requires_human_approval: true`). Nothing in the
codebase applies them. The JSON schema makes `requires_human_approval` a constant
`true`, so a future change that tries to emit anything else fails validation.

## Changes to the original structure, and why

No existing file or folder was renamed, moved or removed. Additions:

| Addition | Why |
|---|---|
| `backend/__init__.py`, `__init__.py` in each backend package, `reviewer/__init__.py` | So `backend.app...` and `reviewer` import from the project root with no `sys.path` hacks. Run with `uvicorn backend.app.main:app` from the root. |
| `reviewer/__init__.py` exposes `review_execution` | One clear entry point so Person 1 does not depend on the reviewer's internals. |
| `pytest.ini`, `tests/__init__.py`, `tests/conftest.py` | Test path config and shared fixtures (in-memory DB). |
| `scripts/generate_samples.py` | Keeps sample data consistent with the code. |
| `shared/sample_data/sample_evidence.json`, `sample_execution_faulty.json`, `sample_review_faulty.json` | The evidence schema needs a sample; the faulty pair shows a reviewer catching a real error. |
| `frontend/index.html`, `vite.config.js`, `src/styles.css`, `.env.example`, `package-lock.json` | Required by Vite or for reproducible installs. |

## Not built yet (deliberately)

Real agent/LLM, authentication, background job queue (task submission is synchronous),
database migrations, pagination, empirical trust calibration, applying improvements.
