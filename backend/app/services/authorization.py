
"""Backend orchestration for evidence-based reviewer authorization."""

import math
from typing import Any

from sqlalchemy.orm import Session

from backend.app.config import Settings
from backend.app.database.models import ExecutionRecord
from reviewer.canary import FAILURE_CATEGORIES, run_canary_suite
from reviewer.reliability import (
    build_reviewer_reliability,
    evaluate_trust_gate,
)


MIN_SOURCE_CASES = 10
MAX_SOURCE_CASES = 100
MAX_SPECIALIST_SOURCE_CASES = 10


class AuthorizationError(ValueError):
    """Raised when source executions cannot safely support authorization."""


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _validate_source_case(
    trace: dict,
    evidence: dict,
    execution_id: str,
) -> None:
    """Accept only structurally valid, completed arithmetic executions."""

    def reject(reason: str) -> None:
        raise AuthorizationError(
            f"Execution '{execution_id}': {reason}"
        )

    if not isinstance(trace, dict) or not isinstance(evidence, dict):
        reject("invalid stored trace or evidence.")

    if trace.get("execution_id") != execution_id:
        reject("inconsistent trace identity.")

    if evidence.get("execution_id") != execution_id:
        reject("inconsistent evidence identity.")

    if trace.get("status") != "completed":
        reject("execution is not completed.")

    if trace.get("fault_injection") is not None:
        reject("execution contains fault-injection data.")

    task = trace.get("task")
    if not isinstance(task, str) or not task.strip():
        reject("task must be non-empty text.")

    claims = evidence.get("verifiable_claims")
    if not isinstance(claims, list) or len(claims) != 1:
        reject("exactly one verifiable arithmetic claim is required.")

    claim = claims[0]
    if not isinstance(claim, dict) or claim.get("kind") != "arithmetic":
        reject("unsupported or malformed arithmetic claim.")

    expression = claim.get("input")
    claimed_result = claim.get("claimed_result")

    if not isinstance(expression, str) or not expression.strip():
        reject("arithmetic expression must be non-empty text.")

    if not _is_finite_number(claimed_result):
        reject("arithmetic claimed_result must be a finite number.")

    tools_used = evidence.get("tools_used")
    if not isinstance(tools_used, list) or "calculator" not in tools_used:
        reject("calculator evidence is missing.")

    steps = trace.get("steps")
    if not isinstance(steps, list):
        reject("trace steps must be a list.")

    if any(not isinstance(step, dict) for step in steps):
        reject("trace contains a malformed step.")

    plan_steps = [step for step in steps if step.get("type") == "plan"]
    calculator_steps = [
        step for step in steps
        if step.get("type") == "tool_call"
        and step.get("name") == "calculator"
    ]
    final_steps = [
        step for step in steps
        if step.get("type") == "final_answer"
    ]

    if len(plan_steps) != 1:
        reject("exactly one plan step is required.")

    if len(calculator_steps) != 1:
        reject("exactly one calculator tool call is required.")

    if len(final_steps) != 1:
        reject("exactly one final-answer step is required.")

    plan_output = plan_steps[0].get("output")
    if not isinstance(plan_output, dict):
        reject("plan step output must be an object.")

    if plan_output.get("tool") != "calculator":
        reject("plan must select the calculator tool.")

    plan_input = plan_output.get("tool_input")
    if not isinstance(plan_input, dict):
        reject("plan tool_input must be an object.")

    if plan_input.get("expression") != expression:
        reject("plan expression does not match the evidence claim.")

    calculator_step = calculator_steps[0]

    step_id = calculator_step.get("step_id")
    if (
        not isinstance(step_id, int)
        or isinstance(step_id, bool)
        or step_id < 1
    ):
        reject("calculator step_id must be a positive integer.")

    if claim.get("step_id") != step_id:
        reject("claim step_id does not match the calculator step.")

    tool_input = calculator_step.get("input")
    if not isinstance(tool_input, dict):
        reject("calculator input must be an object.")

    if tool_input.get("expression") != expression:
        reject("calculator expression does not match the evidence claim.")

    tool_output = calculator_step.get("output")
    if not isinstance(tool_output, dict):
        reject("calculator output must be an object.")

    tool_result = tool_output.get("result")
    if not _is_finite_number(tool_result):
        reject("calculator result must be a finite number.")

    if not math.isclose(
        float(tool_result),
        float(claimed_result),
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        reject("calculator result does not match the evidence claim.")

    final_step = final_steps[0]
    final_output = final_step.get("output")

    if not isinstance(final_output, dict):
        reject("final-answer output must be an object.")

    final_text = final_output.get("text")
    if not isinstance(final_text, str) or not final_text.strip():
        reject("final answer must contain non-empty text.")

    if trace.get("final_answer") != final_text:
        reject("trace final answer is inconsistent.")

    if evidence.get("final_answer") != final_text:
        reject("evidence final answer is inconsistent.")

    if evidence.get("has_final_answer") is not True:
        reject("evidence does not confirm a final answer.")


def authorize_reviewers(
    session: Session,
    execution_ids: list[str],
    settings: Settings,
    *,
    include_specialists: bool = False,
) -> dict[str, Any]:
    """Run canaries and evaluate reviewer authorization from stored executions."""

    if not isinstance(execution_ids, list):
        raise AuthorizationError("execution_ids must be a list.")

    if not MIN_SOURCE_CASES <= len(execution_ids) <= MAX_SOURCE_CASES:
        raise AuthorizationError(
            f"Provide between {MIN_SOURCE_CASES} and "
            f"{MAX_SOURCE_CASES} execution IDs."
        )

    if any(
        not isinstance(item, str) or not item.strip()
        for item in execution_ids
    ):
        raise AuthorizationError(
            "Every execution ID must be non-empty text."
        )

    if len(set(execution_ids)) != len(execution_ids):
        raise AuthorizationError("Duplicate execution IDs are not allowed.")

    if include_specialists:
        if not settings.specialist_reviews_enabled:
            raise AuthorizationError(
                "Specialist authorization is disabled in backend configuration."
            )

        if len(execution_ids) > MAX_SPECIALIST_SOURCE_CASES:
            raise AuthorizationError(
                "Specialist authorization supports at most "
                f"{MAX_SPECIALIST_SOURCE_CASES} source executions per request."
            )

    records = {
        record.execution_id: record
        for record in session.query(ExecutionRecord)
        .filter(ExecutionRecord.execution_id.in_(execution_ids))
        .all()
    }

    missing = sorted(set(execution_ids) - set(records))

    if missing:
        raise AuthorizationError(
            "Unknown execution IDs: " + ", ".join(missing)
        )

    source_cases = []

    for execution_id in execution_ids:
        record = records[execution_id]
        trace = record.trace
        evidence = record.evidence

        _validate_source_case(trace, evidence, execution_id)
        source_cases.append((trace, evidence))

    first_execution, first_evidence = source_cases[0]

    canary_result = run_canary_suite(
        first_execution,
        first_evidence,
        include_specialists=include_specialists,
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout_seconds=settings.ollama_specialist_timeout_seconds,
        source_cases=source_cases,
    )

    reliability = build_reviewer_reliability(canary_result)

    decisions = []

    for reviewer_name in sorted(reliability["reviewers"]):
        for category in FAILURE_CATEGORIES:
            decisions.append(
                evaluate_trust_gate(
                    reliability,
                    reviewer_name,
                    category,
                )
            )

    return {
        "status": "completed",
        "source_execution_count": len(execution_ids),
        "unique_source_cases": canary_result["unique_source_cases"],
        "canary_summary": {
            "total_scenarios": canary_result["total_scenarios"],
            "failure_categories": canary_result["failure_categories"],
            "repetitions_are_independent": False,
        },
        "reliability": reliability,
        "authorization_decisions": decisions,
    }
