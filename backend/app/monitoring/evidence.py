"""Evidence aggregation (Person 1). STATUS: REAL.

Turns an ExecutionTrace into an EvidenceSummary: counts, errors, timing, and
the tool outputs a reviewer can re-check independently ("verifiable claims").
It records observations only; judging them is the reviewer's job.
"""
from collections import Counter

from backend.app.api.schemas import (
    EvidenceError,
    EvidenceSummary,
    FactualEvidence,
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



def _factual_evidence_for(step) -> FactualEvidence | None:
    """Extract factual retrieval observations from a successful tool step."""
    if (
        step.type != "tool_call"
        or step.name != "factual_qa"
        or step.status != "ok"
        or not step.output
    ):
        return None

    output = step.output
    sources = [
        {
            "title": str(source.get("title", "")),
            "url": str(source.get("url", "")),
        }
        for source in output.get("sources", [])
        if isinstance(source, dict)
    ]

    return FactualEvidence(
        step_id=step.step_id,
        question=str(output.get("question") or step.input.get("question", "")),
        answer=str(output.get("answer", "")),
        sources=sources,
        verification_status=output.get("verification_status", "unverified"),
    )


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
        factual_evidence=[
            item for s in trace.steps
            if (item := _factual_evidence_for(s)) is not None
        ],
    )
