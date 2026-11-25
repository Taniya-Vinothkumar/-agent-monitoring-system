"""Controlled canary evaluations for reviewer reliability.

Canaries operate on copied execution/evidence dictionaries. They never modify
live executions, API fault-injection options, or persisted database records.

Detection is category-specific: a generic warning does not count as detection.
"""

import copy
from typing import Any, Callable

from reviewer import review_execution
from reviewer.specialists import run_specialist_reviewers


# The deterministic reviewer can only detect failures covered by its checks.
DETERMINISTIC_CHECKS = {
    "wrong_tool": set(),
    "wrong_arguments": set(),
    "wrong_tool_result": {"tool_results_independently_verified"},
    "inconsistent_answer": {"final_answer_matches_tool_results"},
    "incomplete_answer": {"final_answer_matches_tool_results"},
}

# Specialist checks are matched conservatively by check ID and detail.
# A specialist must explicitly fail a relevant check to receive detection credit.
SPECIALIST_TERMS = {
    "tool_use": {
        "wrong_tool": ("tool_selection", "tool choice", "selected tool"),
        "wrong_arguments": ("argument", "input", "parameter"),
        "wrong_tool_result": (),
        "inconsistent_answer": (),
        "incomplete_answer": (),
    },
    "task_completion": {
        "wrong_tool": (),
        "wrong_arguments": (),
        "wrong_tool_result": (),
        "inconsistent_answer": ("consistency", "consistent", "contradict"),
        "incomplete_answer": ("complete", "addresses_request", "incomplete"),
    },
}

FAILURE_CATEGORIES = (
    "wrong_tool",
    "wrong_arguments",
    "wrong_tool_result",
    "inconsistent_answer",
    "incomplete_answer",
)


def _set_final_answer(execution: dict, evidence: dict, answer: str) -> None:
    """Keep the trace and evidence final-answer fields synchronized."""
    execution["final_answer"] = answer
    evidence["final_answer"] = answer
    evidence["has_final_answer"] = True

    for step in execution["steps"]:
        if step["type"] == "final_answer":
            step["output"] = {"text": answer}
            break


def _set_arithmetic_result(
    execution: dict,
    evidence: dict,
    expression: str,
    result: float,
) -> None:
    """Update the plan, tool call, answer and evidence consistently."""
    for step in execution["steps"]:
        if step["type"] == "plan":
            step["output"]["tool"] = "calculator"
            step["output"]["tool_input"] = {"expression": expression}

        elif step["type"] == "tool_call":
            step["name"] = "calculator"
            step["input"] = {"expression": expression}
            step["output"] = {"result": result}

        elif step["type"] == "final_answer":
            step["input"] = {"tool_result": {"result": result}}

    evidence["tools_used"] = ["calculator"]
    evidence["verifiable_claims"] = [
        {
            "step_id": next(
                step["step_id"]
                for step in execution["steps"]
                if step["type"] == "tool_call"
            ),
            "kind": "arithmetic",
            "input": expression,
            "claimed_result": float(result),
        }
    ]


def _make_scenarios(
    original_execution: dict,
    original_evidence: dict,
) -> list[dict[str, Any]]:
    """Create one clean control and five controlled failure scenarios."""

    scenarios = []

    clean_execution = copy.deepcopy(original_execution)
    clean_evidence = copy.deepcopy(original_evidence)
    clean_execution["fault_injection"] = None

    scenarios.append({
        "scenario": "clean_control",
        "category": None,
        "execution": clean_execution,
        "evidence": clean_evidence,
    })

    # Wrong tool: the arithmetic request is incorrectly sent to text_stats.
    execution = copy.deepcopy(original_execution)
    evidence = copy.deepcopy(original_evidence)

    task = execution["task"]
    word_count = len(task.split())
    longest_word = max(task.split(), key=len)

    for step in execution["steps"]:
        if step["type"] == "plan":
            step["output"]["tool"] = "text_stats"
            step["output"]["tool_input"] = {"text": task}
        elif step["type"] == "tool_call":
            step["name"] = "text_stats"
            step["input"] = {"text": task}
            step["output"] = {
                "word_count": word_count,
                "char_count": len(task),
                "longest_word": longest_word,
            }

    evidence["tools_used"] = ["text_stats"]
    evidence["verifiable_claims"] = [
        {
            "step_id": next(
                s["step_id"] for s in execution["steps"]
                if s["type"] == "tool_call"
            ),
            "kind": "word_count",
            "input": task,
            "claimed_result": word_count,
        }
    ]

    _set_final_answer(
        execution, evidence,
        f"The text contains {word_count} words."
    )

    for step in execution["steps"]:
        if step["type"] == "final_answer":
            step["input"] = {"tool_result": {"word_count": word_count}}
            break
    scenarios.append({
        "scenario": "wrong_tool",
        "category": "wrong_tool",
        "execution": execution,
        "evidence": evidence,
    })

    # Wrong arguments: calculator evaluates only part of the requested expression.
    execution = copy.deepcopy(original_execution)
    evidence = copy.deepcopy(original_evidence)

    wrong_expression = "12 + 8"
    wrong_result = 20.0

    _set_arithmetic_result(
        execution, evidence, wrong_expression, wrong_result
    )
    _set_final_answer(
        execution,
        evidence,
        f"The result of {wrong_expression} is {wrong_result:g}.",
    )
    scenarios.append({
        "scenario": "wrong_arguments",
        "category": "wrong_arguments",
        "execution": execution,
        "evidence": evidence,
    })

    # Wrong result: trace, evidence and answer agree with each other,
    # but the result is mathematically incorrect.
    execution = copy.deepcopy(original_execution)
    evidence = copy.deepcopy(original_evidence)

    expression = evidence["verifiable_claims"][0]["input"]
    _set_arithmetic_result(execution, evidence, expression, 16.0)
    _set_final_answer(
        execution, evidence,
        f"The result of {expression} is 16."
    )
    scenarios.append({
        "scenario": "wrong_tool_result",
        "category": "wrong_tool_result",
        "execution": execution,
        "evidence": evidence,
    })

    # Inconsistent answer: tool result remains correct, final answer is wrong.
    execution = copy.deepcopy(original_execution)
    evidence = copy.deepcopy(original_evidence)

    expression = evidence["verifiable_claims"][0]["input"]
    _set_final_answer(
        execution, evidence,
        f"The result of {expression} is 16."
    )
    scenarios.append({
        "scenario": "inconsistent_answer",
        "category": "inconsistent_answer",
        "execution": execution,
        "evidence": evidence,
    })

    # Incomplete answer: the answer does not provide the requested result.
    execution = copy.deepcopy(original_execution)
    evidence = copy.deepcopy(original_evidence)

    _set_final_answer(
        execution, evidence,
        "I calculated the expression."
    )
    scenarios.append({
        "scenario": "incomplete_answer",
        "category": "incomplete_answer",
        "execution": execution,
        "evidence": evidence,
    })

    return scenarios


def _specialist_detected(role: str, category: str, result: dict) -> bool:
    """Require a completed, explicitly failed, category-relevant check."""
    if result.get("status") != "completed":
        return False

    terms = SPECIALIST_TERMS.get(role, {}).get(category, ())

    for check in result.get("checks", []):
        if check.get("status") != "fail":
            continue

        content = (
            str(check.get("check_id", "")) + " "
            + str(check.get("detail", ""))
        ).lower()

        if any(term in content for term in terms):
            return True

    return False


def _reviewer_detected(
    reviewer_id: str,
    category: str,
    result: dict,
) -> bool:
    if reviewer_id == "rule-based-reviewer":
        expected = DETERMINISTIC_CHECKS.get(category, set())
        return any(
            check["check_id"] in expected and check["status"] == "fail"
            for check in result.get("checks", [])
        )

    role = result.get("role", "")
    return _specialist_detected(role, category, result)


def _clean_false_alarm(reviewer_id: str, result: dict) -> bool:
    """Latency warnings are operational warnings, not integrity detections."""
    if result.get("status") not in (None, "completed"):
        return False

    if reviewer_id == "rule-based-reviewer":
        return any(
            check["status"] == "fail"
            and check["check_id"] != "latency_within_budget"
            for check in result.get("checks", [])
        )

    return (
        result.get("verdict") != "pass"
        or any(c.get("status") == "fail" for c in result.get("checks", []))
    )


def _empty_counts() -> dict:
    return {
        "sample_count": 0,
        "detections": 0,
        "missed_detections": 0,
        "detection_rate": None,
    }


def _rate(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else None


def run_canary_suite(
    execution: dict,
    evidence: dict,
    *,
    include_specialists: bool = False,
    base_url: str = "http://localhost:11434",
    model: str = "qwen2.5:3b",
    timeout_seconds: float = 45.0,
    repetitions: int = 1,
    specialist_runner: Callable = run_specialist_reviewers,
) -> dict:
    """Run controlled canaries and report reviewer detection performance.

    Specialist calls are disabled by default because they require Ollama
    and can take several seconds per reviewer per scenario.

    Repetitions allow repeated AI measurements. Each repetition contains
    one clean control and one sample from each failure category.
    """
    if repetitions < 1:
        raise ValueError("repetitions must be at least 1")

    scenarios = _make_scenarios(execution, evidence)

    metrics = {}
    records = []

    def ensure_reviewer(reviewer_id: str) -> dict:
        if reviewer_id not in metrics:
            metrics[reviewer_id] = {
                "clean_controls": 0,
                "false_alarms": 0,
                "failure_samples": 0,
                "detections": 0,
                "missed_detections": 0,
                "unavailable_reviews": 0,
                "detection_rate": None,
                "false_alarm_rate": None,
                "by_category": {
                    category: _empty_counts()
                    for category in FAILURE_CATEGORIES
                },
            }
        return metrics[reviewer_id]

    for repetition in range(1, repetitions + 1):
        for scenario in scenarios:
            scenario_execution = copy.deepcopy(scenario["execution"])
            scenario_evidence = copy.deepcopy(scenario["evidence"])

            # Every canary is isolated from other samples.
            scenario_execution["execution_id"] = (
                f"canary_{repetition}_{scenario['scenario']}"
            )
            scenario_evidence["execution_id"] = (
                scenario_execution["execution_id"]
            )

            rule_result = review_execution(
                scenario_execution,
                scenario_evidence,
            )

            reviewer_results = {
                "rule-based-reviewer": rule_result
            }

            if include_specialists:
                specialist_results = specialist_runner(
                    scenario_execution,
                    scenario_evidence,
                    base_url=base_url,
                    model=model,
                    timeout_seconds=timeout_seconds,
                )
                for specialist in specialist_results:
                    reviewer_results[specialist["reviewer"]] = specialist

            for reviewer_id, result in reviewer_results.items():
                summary = ensure_reviewer(reviewer_id)
                category = scenario["category"]

                if category is None:
                    summary["clean_controls"] += 1
                    if _clean_false_alarm(reviewer_id, result):
                        summary["false_alarms"] += 1
                else:
                    category_metrics = summary["by_category"][category]
                    category_metrics["sample_count"] += 1
                    summary["failure_samples"] += 1

                    available = result.get("status", "completed") == "completed"
                    if not available:
                        summary["unavailable_reviews"] += 1

                    detected = (
                        available
                        and _reviewer_detected(
                            reviewer_id, category, result
                        )
                    )

                    if detected:
                        category_metrics["detections"] += 1
                        summary["detections"] += 1
                    else:
                        category_metrics["missed_detections"] += 1
                        summary["missed_detections"] += 1

                records.append({
                    "repetition": repetition,
                    "scenario": scenario["scenario"],
                    "category": category,
                    "reviewer": reviewer_id,
                    "status": result.get("status", "completed"),
                    "verdict": result.get("verdict"),
                    "detected": (
                        _reviewer_detected(reviewer_id, category, result)
                        if category is not None
                        and result.get("status", "completed") == "completed"
                        else None
                    ),
                })

    for summary in metrics.values():
        summary["detection_rate"] = _rate(
            summary["detections"], summary["failure_samples"]
        )
        summary["false_alarm_rate"] = _rate(
            summary["false_alarms"], summary["clean_controls"]
        )

        for category_metrics in summary["by_category"].values():
            category_metrics["detection_rate"] = _rate(
                category_metrics["detections"],
                category_metrics["sample_count"],
            )

    return {
        "repetitions": repetitions,
        "scenarios_per_repetition": len(scenarios),
        "total_scenarios": len(scenarios) * repetitions,
        "failure_categories": list(FAILURE_CATEGORIES),
        "reviewer_metrics": metrics,
        "results": records,
    }
