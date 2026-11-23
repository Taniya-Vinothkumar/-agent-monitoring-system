# API contract

Base URL `http://localhost:8000/api`. JSON in, JSON out. Interactive docs at `/docs`.
Response bodies follow `shared/schemas/*.json` (mirrored by `backend/app/api/schemas.py`).
Timestamps are ISO 8601 UTC.

| Method | Path | Success | Body |
|---|---|---|---|
| GET | `/health` | 200 | `{"status": "ok", "app": "..."}` |
| POST | `/tasks` | 201 | `TaskSubmitResponse` |
| GET | `/executions` | 200 | `ExecutionListItem[]`, newest first |
| GET | `/executions/{id}` | 200 | `ExecutionTrace` (`execution.json`) |
| GET | `/executions/{id}/evidence` | 200 | `EvidenceSummary` (`evidence.json`) |
| GET | `/executions/{id}/review` | 200 | `ReviewerResult` (`reviewer.json`) |

## POST /tasks

Runs the whole pipeline synchronously and returns when the review is stored.

```json
// request
{ "task": "What is (12 + 8) * 3 / 4?", "fault_injection": null }
```
- `task`: 1–500 characters.
- `fault_injection`: optional, **test only**: `"wrong_tool_result"` or `"inconsistent_answer"`.

```json
// 201 response
{ "execution_id": "exec_3f9a1c2b7d10", "review_id": "rev_91b0e47a22c4",
  "status": "completed", "verdict": "pass", "trust_score": 0.9444 }
```

`status` is the agent run (`completed` | `failed`). `verdict` is the reviewer's
(`pass` | `needs_attention` | `fail`). A run can be `completed` with verdict `fail`:
that is the reviewer catching a wrong answer.

## GET /executions

```json
[{ "execution_id": "exec_...", "task": "...", "status": "completed",
   "created_at": "2026-11-23T10:30:19Z", "total_duration_ms": 0.17,
   "fault_injection": null, "verdict": "pass", "trust_score": 0.9444 }]
```

## Errors

| Code | When | Body |
|---|---|---|
| 404 | unknown execution id | `{"detail": "Execution not found for 'x'"}` |
| 422 | invalid request body | FastAPI validation error list |
| 500 | the reviewer's output failed schema validation | server error; check the logs |

## Changing the contract

1. Edit `shared/schemas/<name>.json` and `backend/app/api/schemas.py` together.
2. Run `python scripts/generate_samples.py`.
3. Run `pytest`. `tests/test_integration.py` checks every sample against both the JSON
   Schema and the Pydantic models.
4. Tell the other person in the pull request description.

Prefer additive changes (new optional fields). Schemas use `additionalProperties: false`,
so adding a field means updating both sides.
