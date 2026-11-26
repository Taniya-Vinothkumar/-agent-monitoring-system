import json
from pathlib import Path

import pytest

from reviewer.canary import (
    _make_scenarios,
    run_canary_suite,
)

SAMPLES = Path(__file__).resolve().parents[1] / "shared" / "sample_data"


@pytest.fixture
def sample_data():
    execution = json.loads(
        (SAMPLES / "sample_execution.json").read_text(encoding="utf-8")
    )
    evidence = json.loads(
        (SAMPLES / "sample_evidence.json").read_text(encoding="utf-8")
    )
    return execution, evidence


def test_creates_clean_control_and_five_failure_scenarios(sample_data):
    execution, evidence = sample_data

    scenarios = _make_scenarios(execution, evidence)

    assert len(scenarios) == 6
    assert scenarios[0]["scenario"] == "clean_control"

    categories = {
        scenario["category"]
        for scenario in scenarios
        if scenario["category"] is not None
    }

    assert categories == {
        "wrong_tool",
        "wrong_arguments",
        "wrong_tool_result",
        "inconsistent_answer",
        "incomplete_answer",
    }


def test_canaries_do_not_modify_original_data(sample_data):
    execution, evidence = sample_data

    original_execution = json.dumps(execution, sort_keys=True)
    original_evidence = json.dumps(evidence, sort_keys=True)

    _make_scenarios(execution, evidence)

    assert json.dumps(execution, sort_keys=True) == original_execution
    assert json.dumps(evidence, sort_keys=True) == original_evidence


def test_modified_scenarios_keep_final_answer_inputs_consistent(sample_data):
    execution, evidence = sample_data

    scenarios = _make_scenarios(execution, evidence)

    for scenario in scenarios:
        if scenario["category"] not in {
            "wrong_tool",
            "wrong_arguments",
            "wrong_tool_result",
        }:
            continue

        final_step = next(
            step for step in scenario["execution"]["steps"]
            if step["type"] == "final_answer"
        )

        tool_step = next(
            step for step in scenario["execution"]["steps"]
            if step["type"] == "tool_call"
        )

        if scenario["category"] == "wrong_tool":
            assert final_step["input"]["tool_result"]["word_count"] == (
                tool_step["output"]["word_count"]
            )
        else:
            assert final_step["input"]["tool_result"]["result"] == (
                tool_step["output"]["result"]
            )


def test_rule_based_reviewer_reports_expected_detection_rates(sample_data):
    execution, evidence = sample_data

    result = run_canary_suite(execution, evidence)

    metrics = result["reviewer_metrics"]["rule-based-reviewer"]

    assert result["total_scenarios"] == 6
    assert metrics["clean_controls"] == 1
    assert metrics["false_alarms"] == 0
    assert metrics["failure_samples"] == 5
    assert metrics["detections"] == 3
    assert metrics["missed_detections"] == 2
    assert metrics["detection_rate"] == 0.6
    assert metrics["false_alarm_rate"] == 0.0

    categories = metrics["by_category"]

    assert categories["wrong_tool"]["detection_rate"] == 0.0
    assert categories["wrong_arguments"]["detection_rate"] == 0.0
    assert categories["wrong_tool_result"]["detection_rate"] == 1.0
    assert categories["inconsistent_answer"]["detection_rate"] == 1.0
    assert categories["incomplete_answer"]["detection_rate"] == 1.0


def test_repetitions_increase_sample_counts(sample_data):
    execution, evidence = sample_data

    result = run_canary_suite(
        execution,
        evidence,
        repetitions=2,
    )

    metrics = result["reviewer_metrics"]["rule-based-reviewer"]

    assert result["total_scenarios"] == 12
    assert metrics["clean_controls"] == 2
    assert metrics["failure_samples"] == 10
    assert metrics["detections"] == 6
    assert metrics["detection_rate"] == 0.6


def test_repetitions_must_be_positive(sample_data):
    execution, evidence = sample_data

    with pytest.raises(ValueError, match="at least 1"):
        run_canary_suite(execution, evidence, repetitions=0)


def test_specialist_reviewer_results_are_included(sample_data):
    execution, evidence = sample_data

    def fake_specialist_runner(*args, **kwargs):
        return [
            {
                "reviewer": "tool-use-reviewer",
                "role": "tool_use",
                "status": "completed",
                "verdict": "pass",
                "checks": [],
            },
            {
                "reviewer": "task-completion-reviewer",
                "role": "task_completion",
                "status": "completed",
                "verdict": "pass",
                "checks": [],
            },
        ]

    result = run_canary_suite(
        execution,
        evidence,
        include_specialists=True,
        specialist_runner=fake_specialist_runner,
    )

    assert "rule-based-reviewer" in result["reviewer_metrics"]
    assert "tool-use-reviewer" in result["reviewer_metrics"]
    assert "task-completion-reviewer" in result["reviewer_metrics"]

def _make_distinct_arithmetic_case(execution, evidence, number):
    import copy

    execution = copy.deepcopy(execution)
    evidence = copy.deepcopy(evidence)

    expression = f"{number} + 5"
    result = float(number + 5)
    execution_id = f"independent_case_{number}"

    execution["execution_id"] = execution_id
    execution["task"] = f"What is {expression}?"

    for step in execution["steps"]:
        if step["type"] == "plan":
            step["input"]["task"] = execution["task"]
            step["output"]["tool_input"] = {"expression": expression}

        elif step["type"] == "tool_call":
            step["input"] = {"expression": expression}
            step["output"] = {"result": result}

        elif step["type"] == "final_answer":
            step["input"] = {"tool_result": {"result": result}}
            step["output"] = {
                "text": f"The result of {expression} is {result:g}."
            }

    execution["final_answer"] = f"The result of {expression} is {result:g}."

    evidence["execution_id"] = execution_id
    evidence["tools_used"] = ["calculator"]
    evidence["verifiable_claims"] = [{
        "step_id": 2,
        "kind": "arithmetic",
        "input": expression,
        "claimed_result": result,
    }]
    evidence["final_answer"] = execution["final_answer"]

    return execution, evidence


def test_multiple_distinct_source_cases_create_independent_samples(sample_data):
    execution, evidence = sample_data

    cases = [
        _make_distinct_arithmetic_case(execution, evidence, number)
        for number in range(1, 11)
    ]

    result = run_canary_suite(
        execution,
        evidence,
        source_cases=cases,
    )

    diversity = result["evidence_diversity"]

    assert result["source_cases_submitted"] == 10
    assert result["unique_source_cases"] == 10
    assert diversity["source_case_count"] == 10

    for category in result["failure_categories"]:
        assert diversity["independent_samples_by_category"][category] == 10


def test_repeating_same_source_case_does_not_create_independent_samples(sample_data):
    execution, evidence = sample_data

    duplicate_cases = [
        (execution, evidence)
        for _ in range(10)
    ]

    result = run_canary_suite(
        execution,
        evidence,
        source_cases=duplicate_cases,
    )

    assert result["source_cases_submitted"] == 10
    assert result["unique_source_cases"] == 1
    assert result["evidence_diversity"]["source_case_count"] == 1

    for category in result["failure_categories"]:
        assert result["evidence_diversity"]["independent_samples_by_category"][category] == 1


def test_empty_source_cases_are_rejected(sample_data):
    execution, evidence = sample_data

    with pytest.raises(ValueError, match="at least one case"):
        run_canary_suite(
            execution,
            evidence,
            source_cases=[],
        )


def test_wrong_argument_mutation_uses_each_source_expression(sample_data):
    execution, evidence = sample_data

    execution, evidence = _make_distinct_arithmetic_case(
        execution, evidence, 7
    )

    scenarios = _make_scenarios(execution, evidence)
    wrong_arguments = next(
        item for item in scenarios
        if item["category"] == "wrong_arguments"
    )

    claim = wrong_arguments["evidence"]["verifiable_claims"][0]

    assert claim["input"] == "(7 + 5) + 1"
    assert claim["claimed_result"] == 13.0

def test_timestamp_and_duration_changes_do_not_create_independent_cases(sample_data):
    import copy

    from reviewer.canary import _scenario_fingerprint

    execution, evidence = sample_data

    changed_execution = copy.deepcopy(execution)
    changed_evidence = copy.deepcopy(evidence)

    changed_execution["execution_id"] = "another_execution"
    changed_execution["started_at"] = "2027-01-01T10:00:00Z"
    changed_execution["finished_at"] = "2027-01-01T10:00:10Z"
    changed_execution["total_duration_ms"] = 9999

    for step in changed_execution["steps"]:
        step["timestamp"] = "2027-01-01T10:00:05Z"
        step["duration_ms"] = 500

    changed_evidence["execution_id"] = "another_execution"
    changed_evidence["total_duration_ms"] = 9999

    assert _scenario_fingerprint(execution, evidence) == (
        _scenario_fingerprint(changed_execution, changed_evidence)
    )
