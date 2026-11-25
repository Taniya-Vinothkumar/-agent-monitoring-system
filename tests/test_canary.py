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
