"""Trace recording and evidence aggregation (Person 1)."""
import pytest

from backend.app.api.schemas import AgentInfo
from backend.app.monitoring.evidence import aggregate_evidence
from backend.app.monitoring.trace_recorder import TraceRecorder

AGENT = AgentInfo(name="t", version="0", mode="mock_rule_based")


def test_recorder_numbers_and_times_steps():
    rec = TraceRecorder("task", AGENT)
    with rec.step("plan", "planner", {"a": 1}) as s:
        s.output = {"ok": True}
    with rec.step("final_answer", "compose", {}) as s:
        s.output = {"text": "done"}
    trace = rec.finalize("done")
    assert [s.step_id for s in trace.steps] == [1, 2]
    assert trace.status == "completed"
    assert all(s.duration_ms >= 0 for s in trace.steps)
    assert trace.execution_id.startswith("exec_")


def test_recorder_records_error_and_reraises():
    rec = TraceRecorder("task", AGENT)
    with pytest.raises(RuntimeError):
        with rec.step("tool_call", "boom", {}):
            raise RuntimeError("kaput")
    trace = rec.finalize(None)
    assert trace.status == "failed"
    assert trace.steps[0].status == "error" and trace.steps[0].error == "kaput"
    assert trace.steps[0].output is None


def test_evidence_summarises_trace():
    rec = TraceRecorder("task", AGENT)
    with rec.step("plan", "planner", {}) as s:
        s.output = {}
    with rec.step("tool_call", "calculator", {"expression": "1 + 1"}) as s:
        s.output = {"result": 2}
    with rec.step("final_answer", "compose", {}) as s:
        s.output = {"text": "2"}
    ev = aggregate_evidence(rec.finalize("2"))
    assert ev.total_steps == 3 and ev.tool_call_count == 1 and ev.tools_used == ["calculator"]
    assert ev.step_type_counts == {"plan": 1, "tool_call": 1, "final_answer": 1}
    assert ev.has_final_answer and ev.error_count == 0
    assert [(c.kind, c.input, c.claimed_result) for c in ev.verifiable_claims] == [("arithmetic", "1 + 1", 2)]


def test_evidence_collects_errors_and_no_claims_for_failed_tool():
    rec = TraceRecorder("task", AGENT)
    with pytest.raises(ValueError):
        with rec.step("tool_call", "calculator", {"expression": "1/0"}):
            raise ValueError("division by zero")
    ev = aggregate_evidence(rec.finalize(None))
    assert ev.error_count == 1 and ev.errors[0].message == "division by zero"
    assert ev.verifiable_claims == [] and not ev.has_final_answer
