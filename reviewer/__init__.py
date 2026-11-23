"""Reviewer package (Person 2).

Public contract with the backend:

    review_execution(execution: dict, evidence: dict) -> dict

`execution` follows shared/schemas/execution.json, `evidence` follows
shared/schemas/evidence.json, and the returned dict follows
shared/schemas/reviewer.json. Nothing here imports backend code.
"""
from reviewer.audit import audit_review
from reviewer.evaluator import evaluate
from reviewer.improvement import propose_improvements
from reviewer.trust_calibration import calibrate_trust
from reviewer.validation import validate_review


def review_execution(execution: dict, evidence: dict, *, latency_budget_ms: float = 5000.0) -> dict:
    review = evaluate(execution, evidence, latency_budget_ms=latency_budget_ms)
    review["audit"] = audit_review(review, execution, evidence)
    review["trust"] = calibrate_trust(review)
    review["improvements"] = propose_improvements(review)
    validate_review(review)
    return review


__all__ = ["review_execution", "evaluate", "audit_review", "calibrate_trust",
           "propose_improvements", "validate_review"]
