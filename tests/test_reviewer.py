"""Reviewer modules (Person 2). Uses only shared sample data: no backend imports."""
import copy

import pytest

from reviewer import review_execution
from reviewer.audit import audit_review
from reviewer.evaluator import compute_score, derive_verdict, evaluate
from reviewer.improvement import propose_improvements
from reviewer.trust_calibration import calibrate_trust
from reviewer.validation import SchemaValidationError, schema_errors, validate_review
from tests.conftest import load_sample


@pytest.fixture
def execution():
    return load_sample("sample_execution.json")


@pytest.fixture
def evidence():
    return load_sample("sample_evidence.json")


def statuses(review):
    return {c["check_id"]: c["status"] for c in review["checks"]}


def test_clean_run_passes_every_check(execution, evidence):
    review = evaluate(execution, evidence)
    assert set(statuses(review).values()) == {"pass"}
    assert review["score"] == 1.0 and review["verdict"] == "pass"


def test_wrong_tool_result_is_caught_by_recomputation(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["verifiable_claims"][0]["claimed_result"] = 16
    review = evaluate(execution, evidence)
    assert statuses(review)["tool_results_independently_verified"] == "fail"
    assert review["verdict"] == "fail"


def test_inconsistent_final_answer_is_caught(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["final_answer"] = "The result of (12 + 8) * 3 / 4 is 16."
    assert statuses(evaluate(execution, evidence))["final_answer_matches_tool_results"] == "fail"


def test_missing_answer_and_errors(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence.update(has_final_answer=False, final_answer=None, error_count=1,
                    errors=[{"step_id": 2, "message": "boom"}], verifiable_claims=[])
    s = statuses(evaluate(execution, evidence))
    assert s["final_answer_present"] == "fail" and s["no_step_errors"] == "fail"
    assert s["tool_results_independently_verified"] == "skipped"


def test_latency_budget_is_configurable(execution, evidence):
    assert statuses(evaluate(execution, evidence, latency_budget_ms=0.0))["latency_within_budget"] == "fail"


def test_score_and_verdict_rules():
    mk = lambda sev, st: {"severity": sev, "status": st}
    assert compute_score([mk("critical", "pass"), mk("warning", "fail")]) == 0.6
    assert compute_score([mk("critical", "skipped")]) == 0.0
    assert derive_verdict([mk("warning", "fail")]) == "needs_attention"
    assert derive_verdict([mk("critical", "fail")]) == "fail"


def test_audit_passes_on_honest_review_and_catches_tampering(execution, evidence):
    review = evaluate(execution, evidence)
    assert audit_review(review, execution, evidence)["passed"]

    tampered = copy.deepcopy(review)
    tampered["score"] = 0.1
    tampered["checks"][0]["evidence_step_ids"] = [99]
    tampered["checks"].pop()
    result = audit_review(tampered, execution, evidence)
    failed = {f["audit_id"] for f in result["findings"] if f["status"] == "fail"}
    assert not result["passed"]
    assert {"score_reproducible", "evidence_steps_exist", "required_checks_present"} <= failed


def test_trust_is_bounded_and_ordered(execution, evidence):
    review = evaluate(execution, evidence)
    review["audit"] = audit_review(review, execution, evidence)
    good = calibrate_trust(review)
    assert 0 <= good["lower"] <= good["score"] <= good["upper"] <= 1
    assert good["method"] == "beta_prior_uncalibrated" and good["n_checks"] == 6

    bad = copy.deepcopy(review)
    bad["checks"][3]["status"] = "fail"
    capped_critical = calibrate_trust(bad)
    assert capped_critical["score"] <= 0.5 < good["score"] and capped_critical["upper"] <= 0.5
    assert capped_critical["critical_failure_cap_applied"] and not good["critical_failure_cap_applied"]

    warning_only = copy.deepcopy(review)
    warning_only["checks"][5]["status"] = "fail"          # latency: a warning, not critical
    assert 0.5 < calibrate_trust(warning_only)["score"] < good["score"]

    failed_audit = copy.deepcopy(review)
    failed_audit["audit"]["passed"] = False
    capped = calibrate_trust(failed_audit)
    assert capped["score"] <= 0.5 and capped["audit_penalty_applied"]


def test_improvements_are_proposals_only(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["verifiable_claims"][0]["claimed_result"] = 16
    review = evaluate(execution, evidence)
    review["audit"] = audit_review(review, execution, evidence)
    items = propose_improvements(review)
    # Claim altered to 16 while the answer still says 15: both the re-computation and the answer check fail.
    assert {i["target_check"] for i in items} == {"tool_results_independently_verified",
                                                  "final_answer_matches_tool_results"}
    assert all(i["requires_human_approval"] and i["status"] == "proposed" for i in items)


def test_full_review_matches_the_shared_schema(execution, evidence):
    review = review_execution(execution, evidence)
    assert schema_errors(review, "reviewer") == []
    del review["trust"]
    with pytest.raises(SchemaValidationError):
        validate_review(review)

def test_factual_qa_without_evidence_fails(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["tools_used"].append("factual_qa")

    review = evaluate(execution, evidence)
    assert statuses(review)["factual_evidence_contract_satisfied"] == "fail"
    assert review["verdict"] == "fail"


def test_factual_qa_unverified_source_fails(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["tools_used"].append("factual_qa")
    evidence["factual_evidence"] = [{
        "step_id": execution["steps"][0]["step_id"],
        "verification_status": "unverified",
        "sources": [{"title": "Example", "url": "https://example.com"}],
    }]

    review = evaluate(execution, evidence)
    assert statuses(review)["factual_evidence_contract_satisfied"] == "fail"
    assert review["verdict"] == "fail"


def test_factual_qa_verified_evidence_passes_contract(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["tools_used"].append("factual_qa")
    evidence["factual_evidence"] = [{
        "step_id": execution["steps"][0]["step_id"],
        "verification_status": "verified",
        "sources": [{"title": "Example", "url": "https://example.com"}],
    }]

    review = evaluate(execution, evidence)
    assert statuses(review)["factual_evidence_contract_satisfied"] == "pass"
    assert audit_review(review, execution, evidence)["passed"]


def test_factual_audit_detects_missing_required_check(execution, evidence):
    evidence = copy.deepcopy(evidence)
    evidence["tools_used"].append("factual_qa")
    evidence["factual_evidence"] = [{
        "step_id": execution["steps"][0]["step_id"],
        "verification_status": "unverified",
        "sources": [],
    }]

    review = evaluate(execution, evidence)
    review["checks"] = [
        check for check in review["checks"]
        if check["check_id"] != "factual_evidence_contract_satisfied"
    ]

    audit = audit_review(review, execution, evidence)
    assert not audit["passed"]
    assert any(
        finding["audit_id"] == "required_checks_present"
        and finding["status"] == "fail"
        for finding in audit["findings"]
    )

