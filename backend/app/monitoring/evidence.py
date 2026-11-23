"""Evidence aggregation (Person 1). STATUS: REAL.

Turns an ExecutionTrace into an EvidenceSummary: counts, errors, timing, and
the tool outputs a reviewer can re-check independently ("verifiable claims").
It records observations only; judging them is the reviewer's job.
"""
from collections import Counter

from backend.app.api.schemas import (
    EvidenceError,
    EvidenceSummary,
    ExecutionTrace,
    VerifiableClaim,
)


def _claim_for(step) -> VerifiableClaim | None:
    if step.type != "tool_call" or step.status != "ok" or not step.output:
        return None
    if step.name == "calculator" and "result" in step.output:
        return VerifiableClaim(
            step_id=step.step_id, kind="arithmetic",
            input=str(step.input.get("expression", "")), claimed_result=step.output["result"],
        )
    if step.name == "text_stats" and "word_count" in step.output:
        return VerifiableClaim(
            step_id=step.step_id, kind="word_count",
            input=str(step.input.get("text", "")), claimed_result=step.output["word_count"],
        )
    return None


def aggregate_evidence(trace: ExecutionTrace) -> EvidenceSummary:
    tool_steps = [s for s in trace.steps if s.type == "tool_call"]
    errors = [EvidenceError(step_id=s.step_id, message=s.error or "unknown error")
              for s in trace.steps if s.status == "error"]
    tools_used = list(dict.fromkeys(s.name for s in tool_steps))
    return EvidenceSummary(
        execution_id=trace.execution_id,
        total_steps=len(trace.steps),
        step_type_counts=dict(Counter(s.type for s in trace.steps)),
        tool_call_count=len(tool_steps),
        tools_used=tools_used,
        error_count=len(errors),
        errors=errors,
        total_duration_ms=trace.total_duration_ms,
        has_final_answer=trace.final_answer is not None,
        final_answer=trace.final_answer,
        verifiable_claims=[c for s in trace.steps if (c := _claim_for(s))],
    )
