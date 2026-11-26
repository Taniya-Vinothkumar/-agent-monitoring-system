from pathlib import Path
from reviewer.reliability import (
    build_reviewer_reliability,
    evaluate_trust_gate,
)

def make_canary_result(
    *,
    sample_count=10,
    detection_rate=0.9,
    clean_controls=10,
    false_alarm_rate=0.0,
    duplicate_scenarios=False,
):
    detections = round(sample_count * detection_rate)

    records = []

    for index in range(clean_controls):
        records.append({
            "reviewer": "rule-based-reviewer",
            "category": None,
            "scenario_fingerprint": (
                "same-clean" if duplicate_scenarios
                else f"clean-scenario-{index}"
            ),
            "source_fingerprint": (
                "same-source" if duplicate_scenarios
                else f"clean-source-{index}"
            ),
            "status": "completed",
            "false_alarm": index < round(clean_controls * false_alarm_rate),
        })

    for index in range(sample_count):
        records.append({
            "reviewer": "rule-based-reviewer",
            "category": "wrong_tool",
            "scenario_fingerprint": (
                "same-failure" if duplicate_scenarios
                else f"failure-scenario-{index}"
            ),
            "source_fingerprint": (
                "same-source" if duplicate_scenarios
                else f"failure-source-{index}"
            ),
            "status": "completed",
            "detected": index < detections,
            "false_alarm": None,
        })

    return {
        "reviewers": {
            "rule-based-reviewer": {
                "clean_controls": clean_controls,
                "false_alarms": round(clean_controls * false_alarm_rate),
                "false_alarm_rate": false_alarm_rate,
                "by_category": {
                    "wrong_tool": {
                        "sample_count": sample_count,
                        "detections": detections,
                        "missed_detections": sample_count - detections,
                        "detection_rate": detection_rate,
                    }
                },
            }
        },
        "results": records,
    }


def test_current_canary_evidence_is_insufficient():
    canary = make_canary_result(
        sample_count=1,
        detection_rate=0.0,
        clean_controls=1,
    )

    reliability = build_reviewer_reliability(canary)

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is False
    assert gate["status"] == "blocked"
    assert any("diverse" in reason for reason in gate["reasons"])
    assert any("Insufficient" in reason for reason in gate["reasons"])

def test_repeated_scenarios_do_not_bypass_diversity_requirement():
    canary = make_canary_result(sample_count=100, duplicate_scenarios=True)

    reliability = build_reviewer_reliability(
        canary,
    )

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is False
    assert any("diverse" in reason for reason in gate["reasons"])

def test_reviewer_is_authorized_when_all_requirements_are_met():
    canary = make_canary_result(
        sample_count=20,
        detection_rate=0.9,
        clean_controls=20,
        false_alarm_rate=0.05,
    )

    reliability = build_reviewer_reliability(
        canary,
    )

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is True
    assert gate["status"] == "authorized"
    assert gate["reasons"] == []

def test_low_detection_rate_blocks_reviewer():
    canary = make_canary_result(
        sample_count=20,
        detection_rate=0.5,
        clean_controls=20,
    )

    reliability = build_reviewer_reliability(
        canary,
    )

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is False
    assert any("Detection rate" in reason for reason in gate["reasons"])

def test_high_false_alarm_rate_blocks_reviewer():
    canary = make_canary_result(
        sample_count=20,
        detection_rate=0.9,
        clean_controls=20,
        false_alarm_rate=0.2,
    )

    reliability = build_reviewer_reliability(
        canary,
    )

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is False
    assert any("False-alarm rate" in reason for reason in gate["reasons"])

def test_missing_reviewer_is_blocked():
    reliability = build_reviewer_reliability({"reviewers": {}})

    gate = evaluate_trust_gate(
        reliability,
        "unknown-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is False
    assert gate["status"] == "insufficient_evidence"

def test_missing_category_is_blocked():
    canary = make_canary_result()

    reliability = build_reviewer_reliability(
        canary,
    )

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "incomplete_answer",
    )

    assert gate["authorized"] is False
    assert gate["status"] == "insufficient_evidence"

def test_invalid_thresholds_are_rejected():
    canary = make_canary_result()

    try:
        build_reviewer_reliability(
            canary,
            min_detection_rate=1.5,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid detection threshold was accepted")

def test_accepts_actual_canary_output_structure():
    canary = {
        "reviewer_metrics": {
            "rule-based-reviewer": {
                "clean_controls": 10,
                "false_alarms": 0,
                "false_alarm_rate": 0.0,
                "by_category": {
                    "wrong_tool": {
                        "sample_count": 10,
                        "detections": 0,
                        "missed_detections": 10,
                        "detection_rate": 0.0,
                    }
                },
            }
        }
    }

    reliability = build_reviewer_reliability(
        canary,
    )

    assert "rule-based-reviewer" in reliability["reviewers"]

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool",
    )

    assert gate["authorized"] is False
    assert any("Detection rate" in reason for reason in gate["reasons"])

from reviewer.canary import run_canary_suite


def test_canary_to_reliability_to_trust_gate_flow():
    from reviewer.reliability import (
        build_reviewer_reliability,
        evaluate_trust_gate,
    )

    import json

    sample_dir = Path(__file__).resolve().parents[1] / "shared" / "sample_data"
    execution = json.loads((sample_dir / "sample_execution.json").read_text(encoding="utf-8"))
    evidence = json.loads((sample_dir / "sample_evidence.json").read_text(encoding="utf-8"))

    canary_result = run_canary_suite(
        execution,
        evidence,
        include_specialists=False,
        repetitions=1,
    )

    reliability = build_reviewer_reliability(
        canary_result,
    )

    gate = evaluate_trust_gate(
        reliability,
        "rule-based-reviewer",
        "wrong_tool_result",
    )

    assert "rule-based-reviewer" in reliability["reviewers"]
    assert gate["authorized"] is False
    assert gate["status"] == "blocked"
    assert any(
        "diverse" in reason.lower()
        for reason in gate["reasons"]
    )
