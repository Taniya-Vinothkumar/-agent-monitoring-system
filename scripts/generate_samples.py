"""Regenerate shared/sample_data/*.json by running the real pipeline.

    python scripts/generate_samples.py

The samples are real output of the mock agent, evidence aggregation and the
reviewer (no hand-written values), so they stay consistent with the code.
Run it again after changing the pipeline, then commit the result.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.agent.executor import MockAgentExecutor  # noqa: E402
from backend.app.api.schemas import TaskRequest  # noqa: E402
from backend.app.monitoring.evidence import aggregate_evidence  # noqa: E402
from reviewer import review_execution  # noqa: E402

OUT = ROOT / "shared" / "sample_data"
TASK = "What is (12 + 8) * 3 / 4?"


def build(request: TaskRequest):
    trace = MockAgentExecutor().run(request)
    evidence = aggregate_evidence(trace)
    trace_d, evidence_d = trace.model_dump(mode="json"), evidence.model_dump(mode="json")
    return trace_d, evidence_d, review_execution(trace_d, evidence_d)


def dump(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT / name)


if __name__ == "__main__":
    t, e, r = build(TaskRequest(task=TASK))
    dump("sample_execution.json", t)
    dump("sample_evidence.json", e)
    dump("sample_review.json", r)

    # Same task, but the tool's recorded result is wrong by one: the reviewer should catch it.
    t, _, r = build(TaskRequest(task=TASK, fault_injection="wrong_tool_result"))
    dump("sample_execution_faulty.json", t)
    dump("sample_review_faulty.json", r)
